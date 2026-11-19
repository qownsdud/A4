"""네트워크·모델 없이 실 알고리즘과 승인 경계 및 JobManager 계약을 검증합니다."""
import asyncio
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
import httpx
import pytest
from PIL import Image, ImageDraw
from art_artwork_pipeline.pipeline_runner import save_photo, prepare_artwork, atomic_json, job_directory
from art_artwork_pipeline.path_planner.drawing_plan import validate_plan, build_plan
from art_artwork_pipeline.path_planner.path_optimizer import optimize_plan
from art_artwork_pipeline.puzzle.colors import balanced_cells
from art_artwork_pipeline.calligraphy.generator import generate_strokes
import sys
from art_artwork_pipeline.plan import load_plan
_JM_SRC = Path(__file__).resolve().parents[2] / 'control/ros2_ws/src/art_job_manager'
if str(_JM_SRC) not in sys.path:
    sys.path.insert(0, str(_JM_SRC))
from art_job_manager.production_engine import ProductionEngine
from art_kiosk import server
from art_kiosk_bridge.http_api import create_app
from art_kiosk_bridge.schemas import JobCommandReply

def photo():
    image=Image.new('RGB',(100,140),'white')
    ImageDraw.Draw(image).rectangle((20,20,80,100),outline='black',width=3)
    buffer=io.BytesIO()
    image.save(buffer,'PNG')
    return buffer.getvalue()

def lineart(root,job='TEST'):
    directory=save_photo(job,photo(),root)
    prepare_artwork(job,stage='LINEART',input_path=str(directory/'photo.png'),root=root)
    return directory

def confirm(directory):
    atomic_json(directory/'job_metadata.json',dict(job_id=directory.name,confirmed=True))

def test_cv_vector_svg_sha_and_no_overwrite(tmp_path):
    directory=lineart(tmp_path)
    with pytest.raises(ValueError,match='확인'):
        prepare_artwork('TEST',stage='PLAN',input_path=str(directory/'lineart.png'),root=tmp_path)
    confirm(directory)
    result=prepare_artwork('TEST',stage='PLAN',input_path=str(directory/'lineart.png'),root=tmp_path,text='Hi')
    plan=json.loads(Path(result['plan_path']).read_text())
    assert validate_plan(plan)
    assert {'artwork','calligraphy'}=={s['layer'] for s in plan['strokes']}
    assert '<svg' in Path(result['preview_path']).read_text()
    summary=load_plan('TEST',result['plan_path'],plan_root=tmp_path)
    assert summary.sha256==hashlib.sha256(Path(result['plan_path']).read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        prepare_artwork('TEST',stage='PLAN',input_path=str(directory/'lineart.png'),root=tmp_path)

def test_colors_and_layers_preserved():
    assert Counter(balanced_cells())==Counter(PEN_1=6,PEN_2=5,PEN_3=5)
    assert balanced_cells(23)==balanced_cells(23)
    plan=build_plan([{'points':[[10,10],[20,20]]}],100,100)
    plan['strokes'].extend(generate_strokes('Hi'))
    for i,s in enumerate(plan['strokes']):
        s.update(stroke_id=i+1,execution_order=i)
    before=Counter((s['pen_id'],s['layer']) for s in plan['strokes'])
    result=optimize_plan(plan,backend='opencv',merge_tolerance_mm=0,curve_step_mm=0)
    assert set(before)=={(s['pen_id'],s['layer']) for s in result['strokes']}
    assert result['grid']==plan['grid']
    assert validate_plan(result)
    mixed = generate_strokes('안녕! Hi ★')
    assert len(mixed) > 0 and all(s['layer'] == 'calligraphy' for s in mixed)
    with pytest.raises(ValueError):
        generate_strokes('안녕\n줄바꿈')

def test_path_isolation_cancellation_and_failed_publication(tmp_path):
    first=lineart(tmp_path,'FIRST')
    second=lineart(tmp_path,'SECOND')
    with pytest.raises(ValueError):
        job_directory('../escape',tmp_path)
    with pytest.raises(ValueError):
        prepare_artwork('FIRST',stage='PLAN',input_path=str(second/'lineart.png'),root=tmp_path)
    confirm(first)
    with pytest.raises(InterruptedError):
        prepare_artwork('FIRST',stage='PLAN',input_path=str(first/'lineart.png'),root=tmp_path,cancel=lambda:True)
    assert not (first/'drawing_plan.json').exists()
    assert not (first/'.processing').exists()
    with pytest.raises(ValueError):
        prepare_artwork('FIRST',stage='PLAN',input_path=str(first/'lineart.png'),root=tmp_path,text='한글\n오류')
    assert not (first/'drawing_plan.json').exists()
    out = prepare_artwork('FIRST',stage='PLAN',input_path=str(first/'lineart.png'),root=tmp_path,text='한글! ★')
    assert Path(out['plan_path']).is_file()

def test_kiosk_bridge_real_pipeline_manager_approval(monkeypatch,tmp_path):
    monkeypatch.setenv('ART_JOB_PLAN_ROOT',str(tmp_path))
    monkeypatch.setenv('ART_LINEART_METHOD','cv')
    monkeypatch.delenv('ART_ADMIN_TOKEN', raising=False)
    engine=ProductionEngine(tmp_path/'jobs.db',plan_root=tmp_path)
    class Bridge:
        def is_ready(self): return True
        async def prepare_artwork(self,body):
            return prepare_artwork(**body.dict())
        async def create_job(self,job_id,plan_path):
            r=engine.create_job(job_id,plan_path)
            return JobCommandReply(accepted=r.accepted,job_id=r.job_id,manager_state=r.state,error_code=r.error_code,message=r.message)
    monkeypatch.setattr(server.app.state,'bridge_transport',httpx.ASGITransport(app=create_app(Bridge())),raising=False)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://kiosk.test') as client:
            response=await client.post('/api/kiosk/photo',files={'photo':('photo.png',photo(),'image/png')})
            assert response.status_code==200,response.text
            job=response.headers['x-job-id']
            response=await client.post('/api/kiosk/confirm',files={'image':('line.png',response.content)},data={'job_id':job})
            assert response.status_code==200,response.text
            assert not engine.statuses()
            path=f'/api/admin/artwork/{job}/prepare'
            assert (await client.post(path, headers={'Origin':'http://other.test'})).status_code==403
            auth={}
            response=await client.post(path,headers=auth)
            assert response.status_code==200,response.text
            assert not engine.statuses()
            result=await client.post('/api/admin/jobs',headers=auth,json={'job_id':job,'plan_path':response.json()['plan_path']})
            assert result.status_code==202,result.text
            assert engine.status(job)['state']=='QUEUED'
    try:
        asyncio.run(run())
    finally:
        engine.close()
