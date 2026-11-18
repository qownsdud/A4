import asyncio,io,json,time,importlib.util,threading
from pathlib import Path
import pytest,httpx
from PIL import Image,ImageDraw
from art_kiosk import server,workflow
from art_kiosk_bridge.http_api import create_app
from art_kiosk_bridge.errors import ArtworkFailed
from art_kiosk_bridge.schemas import JobCommandReply,JobStatusReply
from art_artwork_pipeline.pipeline_runner import prepare_artwork
from fake_execution import FakeExecutionBackend

AUTH={}
def photo():
    image=Image.new('RGB',(80,110),'white');ImageDraw.Draw(image).rectangle((15,15,65,90),outline='black',width=3)
    b=io.BytesIO();image.save(b,'PNG');return b.getvalue()
class Port:
    def __init__(self,engine):self.engine=engine;self.creates=0;self.stale=False
    def is_ready(self):return True
    async def prepare_artwork(self,body):
        await asyncio.sleep(.01)
        try:
            return prepare_artwork(**body.dict())
        except ValueError as exc:
            raise ArtworkFailed(str(exc)) from exc
    async def create_job(self,job_id,plan_path):
        self.creates+=1;r=self.engine.create_job(job_id,plan_path)
        return JobCommandReply(accepted=r.accepted,job_id=r.job_id,manager_state=r.state,error_code=r.error_code,message=r.message)
    def get_status(self,job_id):
        r=self.engine.status(job_id)
        return JobStatusReply(**r,observed_at_unix=time.time()-(30 if self.stale else 0)) if r else None
    async def control_job(self,job_id,command,request_id):
        if command=='REPLACE' and self.engine.status(job_id) and self.engine.status(job_id)['state'] in ('STOPPED','COMPLETED'):
            return JobCommandReply(accepted=True,job_id=job_id,manager_state='STOPPED',error_code='',message='시험 종료 관측')
        r=self.engine.control_job(job_id,command,request_id)
        return JobCommandReply(accepted=r.accepted,job_id=r.job_id,manager_state=r.state,error_code=r.error_code,message=r.message)
@pytest.fixture
def env(monkeypatch,tmp_path):
    monkeypatch.setenv('ART_JOB_PLAN_ROOT',str(tmp_path/'jobs'))
    monkeypatch.setenv('ART_LINEART_METHOD','cv')
    engine=FakeExecutionBackend(plan_root=tmp_path/'jobs');port=Port(engine)
    monkeypatch.setattr(server.app.state,'bridge_transport',httpx.ASGITransport(app=create_app(port)),raising=False)
    yield engine,port
    engine.close()
async def client_run(fn):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://review.test') as c:return await fn(c)
async def prepare(c,text='Hi'):
    r=await c.post('/api/kiosk/prepare',files={'photo':('photo.png',photo())},data={'text':text})
    assert r.status_code==200,r.text
    return r.json()
async def draw(c,p):return await c.post('/api/kiosk/draw',json={'ticket':p['ticket']})

def test_real_photo_text_plan_svg_without_registration(env):
    engine,port=env
    async def check(c):
        p=await prepare(c)
        assert not engine.statuses()
        d=workflow.job_directory(p['job_id']);plan=json.loads((d/'drawing_plan.json').read_text());meta=json.loads((d/'job_metadata.json').read_text())
        assert {'artwork','calligraphy'}=={s['layer'] for s in plan['strokes']}
        assert meta['text']=='Hi' and meta['confirmed'] is False
        r=await c.get(p['preview_url'],headers={'X-Preview-Ticket':p['ticket']});assert r.status_code==200 and 'data-layer="calligraphy"' in r.text
        assert (await c.get('/api/kiosk/current')).json()['text']=='Hi'
    asyncio.run(client_run(check))

def test_single_click_and_repeated_start_one_registration(env):
    engine,port=env
    async def check(c):
        p=await prepare(c)
        assert (await draw(c,p)).status_code==202
        assert (await draw(c,p)).status_code==202
        assert port.creates==1 and engine.status(p['job_id'])['state']=='DISPATCHING'
        assert (await c.get('/api/kiosk/current')).json()['status']['job_id']==p['job_id']
    asyncio.run(client_run(check))

def test_active_or_paused_job_allows_new_plan_but_blocks_new_execution(env):
    engine,port=env
    async def check(c):
        p=await prepare(c);await draw(c,p)
        for phase in ('QUEUED','PAUSED','RECOVERY_REQUIRED'):
            if phase!='QUEUED':
                engine.confirm_state(p['job_id'],phase)
            r=await c.post('/api/kiosk/prepare',files={'photo':('p.png',photo())})
            assert r.status_code==200,r.text
            assert (await draw(c,r.json())).status_code==409
            assert workflow.read_execution()['job_id']==p['job_id']
        assert len(engine.statuses())==1 and port.creates==1
    asyncio.run(client_run(check))

def test_new_preview_invalidates_old_ticket(env):
    async def check(c):
        first=await prepare(c,'Hi');second=await prepare(c,'A')
        assert first['job_id']!=second['job_id']
        assert (await draw(c,first)).status_code==409
        assert (await draw(c,second)).status_code==202
    asyncio.run(client_run(check))

def test_concurrent_preparation_is_rejected(env):
    async def check(c):
        async def make():return await c.post('/api/kiosk/prepare',files={'photo':('p.png',photo())})
        r=await asyncio.gather(make(),make());assert sorted(x.status_code for x in r)==[200,409]
    asyncio.run(client_run(check))

def test_lost_registration_response_reconciles_without_resubmit(env,monkeypatch):
    engine,port=env
    class Lost(httpx.AsyncBaseTransport):
        def __init__(self):self.inner=httpx.ASGITransport(app=create_app(port));self.lost=False
        async def handle_async_request(self,request):
            r=await self.inner.handle_async_request(request)
            if request.url.path=='/bridge/jobs' and not self.lost:
                self.lost=True;raise httpx.ReadTimeout('등록 후 응답 유실',request=request)
            return r
    monkeypatch.setattr(server.app.state,'bridge_transport',Lost())
    async def check(c):
        p=await prepare(c);assert (await draw(c,p)).status_code==504
        assert workflow.read_state()['phase']=='UNKNOWN_SUBMISSION'
        assert (await draw(c,p)).status_code==202
        assert port.creates==1
    asyncio.run(client_run(check))

def test_admin_auto_target_same_origin_pause_resume_cancel(env):
    engine,port=env
    async def check(c):
        p=await prepare(c);await draw(c,p);job=p['job_id']
        assert engine.confirm_state(job,'DRAWING')
        body=dict(command='PAUSE',request_id='P1',expected_job_id=job)
        assert (await c.post('/api/admin/current/control',json=body,headers={'Origin':'http://other.test'})).status_code==403
        for _ in range(2):assert (await c.post('/api/admin/current/control',json=body,headers=AUTH)).status_code==202
        assert engine.status(job)['state']=='PAUSING'
        engine.confirm_state(job,'PAUSED')
        assert (await c.get('/api/kiosk/current')).json()['status']['state']=='PAUSED'
        body.update(command='RESUME',request_id='R1');assert (await c.post('/api/admin/current/control',json=body,headers=AUTH)).status_code==202
        body.update(command='CANCEL',request_id='C1');assert (await c.post('/api/admin/current/control',json=body,headers=AUTH)).status_code==202
        assert engine.status(job)['state']=='STOPPED'
        # 안전한 최종 상태 이후 새 작업을 준비할 수 있습니다.
        next_job=await prepare(c,'A');assert next_job['job_id']!=job
        assert (await c.post('/api/admin/current/control',json=body,headers=AUTH)).status_code==409
    asyncio.run(client_run(check))

def test_invalid_text_image_and_plan_tampering(env):
    engine,port=env
    async def check(c):
        assert (await c.post('/api/kiosk/prepare',files={'photo':('p.png',photo())},data={'text':'한글'})).status_code==422
        assert (await c.post('/api/kiosk/prepare',files={'photo':('p.png',b'bad')})).status_code==400
        p=await prepare(c);d=workflow.job_directory(p['job_id']);plan=d/'drawing_plan.json';plan.write_text(plan.read_text()+' ')
        assert (await draw(c,p)).status_code==409 and port.creates==0
    asyncio.run(client_run(check))

def test_stale_status_blocks_control_and_new_job(env):
    engine,port=env
    async def check(c):
        p=await prepare(c);await draw(c,p);port.stale=True
        body=dict(command='CANCEL',request_id='C1',expected_job_id=p['job_id'])
        assert (await c.post('/api/admin/current/control',headers=AUTH,json=body)).status_code==409
        assert (await c.get('/api/kiosk/current')).json()['status']['stale']
        next_plan=await prepare(c)
        assert (await draw(c,next_plan)).status_code==409 and port.creates==1
    asyncio.run(client_run(check))

def test_cross_origin_start_and_arbitrary_path_rejected(env):
    async def check(c):
        p=await prepare(c)
        assert (await c.post('/api/kiosk/draw',headers={'Origin':'http://evil.test'},json={'ticket':p['ticket']})).status_code==403
        assert (await c.post('/api/kiosk/draw',json={'ticket':p['ticket'],'plan_path':'/etc/passwd'})).status_code==422
    asyncio.run(client_run(check))

def test_unknown_processing_not_replaced(env):
    workflow.save_state(dict(version=1,job_id='UNCERTAIN',phase='UNKNOWN_PREPARATION',ticket='x',text=''))
    async def check(c):assert (await c.post('/api/kiosk/prepare',files={'photo':('p.png',photo())})).status_code==409
    asyncio.run(client_run(check))

def test_static_pages_and_no_manual_id_forms(env):
    async def check(c):
        user=(await c.get('/')).text
        admin=(await c.get('/admin')).text
        for name in ('app.js','admin.js','style.css'):
            assert (await c.get('/static/'+name)).status_code==200
        assert 'id="calligraphyText"' in user and 'id="btnDraw"' in user
        assert 'jobIdInput' not in user and 'jobWatchForm' not in user
        assert 'planPath' not in admin and 'prepareJobId' not in admin and 'adminJobId' not in admin
        assert all(name in user for name in ('btnPause','btnResume','btnRestart'))
        assert (await c.get('/admin')).status_code==307
    asyncio.run(client_run(check))


def test_current_pointer_survives_module_reload(env):
    import importlib
    engine,port=env
    async def check(c):
        p=await prepare(c);await draw(c,p)
        importlib.reload(workflow)
        r=await c.get('/api/kiosk/current')
        assert r.status_code==200 and r.json()['job_id']==p['job_id']
        assert (await draw(c,p)).status_code==202 and port.creates==1
    asyncio.run(client_run(check))

def test_manager_restart_recovery_stays_blocked(env,monkeypatch):
    _,port=env
    async def check(c):
        p=await prepare(c);await draw(c,p)
        monkeypatch.setattr(port,'get_status',lambda _:None)
        response=await c.get('/api/kiosk/current')
        assert response.status_code==200 and response.json()['can_prepare'] is True
        assert response.json()['can_draw'] is False
        next_plan=await prepare(c)
        assert (await draw(c,next_plan)).status_code==409 and port.creates==1
    asyncio.run(client_run(check))


def test_artwork_and_phrase_have_separate_a4_regions(env):
    async def check(c):
        p=await prepare(c,'Hi')
        plan=json.loads((workflow.job_directory(p['job_id'])/'drawing_plan.json').read_text())
        artwork=[point for s in plan['strokes'] if s['layer']=='artwork' for point in s['points_mm']]
        phrase=[point for s in plan['strokes'] if s['layer']=='calligraphy' for point in s['points_mm']]
        assert artwork and phrase
        assert plan['paper_mm']=={'width':297.,'height':210.}
        assert all(20<=x<=277 and 20<=y<=160 for x,y in artwork)
        assert min(y for x,y in phrase)>=165
        assert max(y for x,y in phrase)<=190
    asyncio.run(client_run(check))


def test_phrase_edit_reuses_lineart_and_preserves_previous_plan(env):
    engine,port=env
    original=port.prepare_artwork
    stages=[]
    async def tracking(body):
        stages.append(body.stage)
        return await original(body)
    port.prepare_artwork=tracking
    async def check(c):
        first=await prepare(c,'Hi')
        old=workflow.job_directory(first['job_id'])/'drawing_plan.json'
        before=old.read_bytes()
        second=await prepare(c,'Hello')
        assert stages==['LINEART','PLAN','PLAN']
        assert old.read_bytes()==before and first['job_id']!=second['job_id']
    asyncio.run(client_run(check))

def test_prepare_response_replay_and_owned_preview_recovery(env):
    async def check(c):
        data={'text':'Hi','request_id':'PREPARE_1'}
        r=await c.post('/api/kiosk/prepare',files={'photo':('photo.png',photo())},data=data)
        assert r.status_code==200,r.text
        prepared=r.json()
        replay=await c.post('/api/kiosk/prepare',files={'photo':('photo.png',photo())},data=data)
        assert replay.status_code==200 and replay.json()['ticket']==prepared['ticket']
        public=(await c.get('/api/kiosk/current')).json()
        assert 'ticket' not in public and 'prepare_request_id' not in public
        assert (await c.get('/api/kiosk/current',headers={'X-Prepare-Request':'PREPARE_1'})).json()['ticket']==prepared['ticket']
        data['text']='A'
        assert (await c.post('/api/kiosk/prepare',files={'photo':('photo.png',photo())},data=data)).status_code==409
    asyncio.run(client_run(check))

def test_admin_media_is_same_origin_and_target_bound(env):
    async def check(c):
        p=await prepare(c)
        assert (await c.get('/api/admin/current')).status_code==200
        current=await c.get('/api/admin/current',headers=AUTH)
        assert current.status_code==200 and current.json()['text']=='Hi'
        path=current.json()['photo_url']
        assert (await c.get(path,headers={'Origin':'http://other.test'})).status_code==403
        assert (await c.get(path,headers=AUTH)).status_code==409
        assert (await c.get(path,headers={**AUTH,'X-Expected-Job-Id':p['job_id']})).status_code==200
        assert (await c.get(current.json()['preview_url'],headers={**AUTH,'X-Expected-Job-Id':p['job_id']})).status_code==200
        assert (await c.get('/api/kiosk/current/photo')).status_code==409
        assert (await c.get('/api/kiosk/current/photo',headers={'X-Preview-Ticket':p['ticket']})).status_code==200
    asyncio.run(client_run(check))

def test_legacy_registration_cannot_bypass_current_user_confirmation(env):
    async def check(c):
        p=await prepare(c)
        r=await c.post('/api/admin/jobs',headers=AUTH,json={'job_id':p['job_id'],'plan_path':str(workflow.job_directory(p['job_id'])/'drawing_plan.json')})
        assert r.status_code==409
        assert (await draw(c,p)).status_code==202
    asyncio.run(client_run(check))

def test_failed_blank_photo_does_not_lock_next_input(env):
    async def check(c):
        b=io.BytesIO();Image.new('RGB',(80,110),'white').save(b,'PNG')
        r=await c.post('/api/kiosk/prepare',files={'photo':('blank.png',b.getvalue())})
        assert r.status_code==422,r.text
        assert (await c.get('/api/kiosk/current')).json()['can_prepare'] is True
        await prepare(c)
    asyncio.run(client_run(check))


def test_finished_preparation_is_recovered_after_lost_web_response(env):
    async def check(c):
        p=await prepare(c)
        data=workflow.read_state()
        data['phase']='UNKNOWN_PREPARATION'
        workflow.save_state(data)
        r=await c.get('/api/kiosk/current',headers={'X-Prepare-Request':data['prepare_request_id']})
        assert r.status_code==200
        assert r.json()['phase']=='PREVIEW' and r.json()['ticket']==p['ticket']
        assert env[1].creates==0
    asyncio.run(client_run(check))


def test_unavailable_pipeline_allows_retry_without_false_completion(env):
    from art_kiosk_bridge.errors import ServiceUnavailable
    engine,port=env
    original=port.prepare_artwork
    async def absent(body):raise ServiceUnavailable('시험용 서버 미연결')
    port.prepare_artwork=absent
    async def check(c):
        r=await c.post('/api/kiosk/prepare',files={'photo':('p.png',photo())})
        assert r.status_code==503
        current=(await c.get('/api/kiosk/current')).json()
        assert current['phase']=='PREPARE_FAILED' and current['can_prepare']
        assert not engine.statuses()
        port.prepare_artwork=original
        await prepare(c)
    asyncio.run(client_run(check))


def test_changed_model_never_reuses_old_cv_preview(env,monkeypatch):
    _,port=env
    async def check(c):
        await prepare(c)
        called=[]
        async def unavailable_model(body):
            called.append((body.stage,body.method))
            raise ArtworkFailed('시험용 모델 미설치')
        monkeypatch.setattr(port,'prepare_artwork',unavailable_model)
        monkeypatch.setenv('ART_LINEART_METHOD','mfl_ld')
        result=await c.post('/api/kiosk/prepare',files={'photo':('photo.png',photo())},data={'text':'Hi'})
        assert result.status_code==422
        assert called==[('LINEART','mfl_ld')]
    asyncio.run(client_run(check))


def test_lineart_only_does_not_replace_unknown_robot_job_or_register_plan(env):
    engine,port=env
    async def check(c):
        p=await prepare(c)
        assert (await draw(c,p)).status_code==202
        # 프로세스 재시작처럼 등록된 작업의 관측을 잃어도 사진 처리는 독립적입니다.
        engine.rows.clear()
        assert (await c.get('/api/kiosk/current')).json()['can_draw'] is False
        before=workflow.state_path().read_bytes()
        creates=port.creates
        response=await c.post('/api/kiosk/lineart',files={'photo':('next.png',photo())},data={'detail':'73'})
        assert response.status_code==200,response.text
        result=response.json()
        assert result['preview_only'] is True and result['image_data'].startswith('data:image/png;base64,')
        assert 'ticket' not in result
        assert workflow.state_path().read_bytes()==before and port.creates==creates
        directory=workflow.job_directory(result['job_id'])
        assert (directory/'lineart.png').is_file()
        assert not (directory/'drawing_plan.json').exists()
        assert (await c.post('/api/kiosk/draw',json={'ticket':'NOT_A_TICKET'})).status_code==409
        assert (await c.post('/api/kiosk/lineart',headers={'Origin':'http://other.test'},files={'photo':('p.png',photo())})).status_code==403
    asyncio.run(client_run(check))


def test_lineart_only_rejects_invalid_input_without_changing_current_job(env):
    async def check(c):
        p=await prepare(c)
        before=workflow.state_path().read_bytes()
        response=await c.post('/api/kiosk/lineart',files={'photo':('bad.png',b'bad')})
        assert response.status_code==400
        assert workflow.state_path().read_bytes()==before
    asyncio.run(client_run(check))


def test_new_draft_keeps_old_pause_target_and_starts_only_after_old_terminal(env):
    engine,port=env
    async def check(c):
        old=await prepare(c,'Old');await draw(c,old)
        engine.confirm_state(old['job_id'],'DRAWING')
        new=await prepare(c,'Next')
        snapshot=(await c.get('/api/kiosk/current')).json()
        assert snapshot['job_id']==new['job_id'] and snapshot['execution_job_id']==old['job_id']
        assert snapshot['can_prepare'] and snapshot['can_draw']
        response=await c.post('/api/kiosk/current/control',json=dict(expected_job_id=old['job_id'],command='PAUSE',request_id='OLD_PAUSE'))
        assert response.status_code==202 and engine.status(old['job_id'])['state']=='PAUSING'
        assert (await c.post('/api/kiosk/current/control',json=dict(expected_job_id=new['job_id'],command='PAUSE',request_id='DRAFT_PAUSE'))).status_code==409
        engine.confirm_state(old['job_id'],'STOPPED')
        assert (await c.get('/api/kiosk/current')).json()['can_draw']
        assert (await draw(c,new)).status_code==202 and port.creates==2
        assert workflow.read_execution()['job_id']==new['job_id']
    asyncio.run(client_run(check))


def test_pause_is_not_locked_out_while_next_picture_is_processing(env,monkeypatch):
    engine,port=env
    original=port.prepare_artwork
    async def check(c):
        old=await prepare(c);await draw(c,old);engine.confirm_state(old['job_id'],'DRAWING')
        entered=asyncio.Event();release=asyncio.Event()
        async def slow(body):
            entered.set();await release.wait();return await original(body)
        monkeypatch.setattr(port,'prepare_artwork',slow)
        task=asyncio.create_task(c.post('/api/kiosk/prepare',files={'photo':('next.png',photo())},data={'text':'Next'}))
        await asyncio.wait_for(entered.wait(),2)
        try:
            response=await c.post('/api/kiosk/current/control',json=dict(expected_job_id=old['job_id'],command='PAUSE',request_id='WHILE_PREPARING'))
            assert response.status_code==202 and engine.status(old['job_id'])['state']=='PAUSING'
        finally:
            release.set()
        assert (await task).status_code==200
    asyncio.run(client_run(check))


def test_operator_recovery_keeps_new_plan_and_requires_actual_stop_response(env,monkeypatch):
    engine,port=env
    async def check(c):
        old=await prepare(c);await draw(c,old)
        new=await prepare(c,'Next')
        engine.rows.clear()
        snapshot=(await c.get('/api/kiosk/current')).json()
        assert snapshot['can_draw']
        body=dict(expected_job_id=old['job_id'],request_id='RECOVER',operator_confirmed_stopped=False)
        assert (await c.post('/api/kiosk/recover-execution',json=body)).status_code==422
        body['operator_confirmed_stopped']=True
        original=workflow.bridge_request
        refused={'value':True}
        calls=[]
        async def transport(request,method,path,**kwargs):
            if path.endswith('/control') and kwargs.get('body',{}).get('command')=='RECONCILE':
                calls.append(kwargs['body'])
                if refused['value']:
                    from fastapi import HTTPException
                    raise HTTPException(409,'실제 정지 확인 거절')
                return dict(accepted=True,job_id=old['job_id'],manager_state='STOPPED',error_code='')
            return await original(request,method,path,**kwargs)
        monkeypatch.setattr(workflow,'bridge_request',transport)
        assert (await c.post('/api/kiosk/recover-execution',json=body)).status_code==409
        assert not workflow.read_execution().get('execution_closed')
        refused['value']=False
        assert (await c.post('/api/kiosk/recover-execution',json=body)).status_code==200
        assert workflow.read_state()['job_id']==new['job_id']
        assert workflow.read_execution()['execution_closed']
        snapshot=(await c.get('/api/kiosk/current')).json()
        assert snapshot['can_draw'] and not snapshot['can_recover']
        assert (await c.post('/api/kiosk/recover-execution',json=body)).status_code==200
        assert len(calls)==2
        assert (await draw(c,new)).status_code==202
    asyncio.run(client_run(check))


def test_new_drawing_automatically_replaces_previous_without_checkbox(env,monkeypatch):
    engine,port=env
    original=port.control_job
    calls=[]
    async def replacement(job_id,command,request_id):
        if command=='REPLACE':
            calls.append(job_id)
            engine.confirm_state(job_id,'STOPPED')
            return JobCommandReply(accepted=True,job_id=job_id,manager_state='STOPPED',error_code='',message='시험 관측 정지·정리 완료')
        return await original(job_id,command,request_id)
    monkeypatch.setattr(port,'control_job',replacement)
    async def check(c):
        old=await prepare(c);assert (await draw(c,old)).status_code==202
        engine.confirm_state(old['job_id'],'DRAWING')
        new=await prepare(c,'Next')
        old_plan=(workflow.job_directory(old['job_id'])/'drawing_plan.json').read_bytes()
        assert (await c.get('/api/kiosk/current')).json()['can_draw']
        result=await draw(c,new)
        assert result.status_code==202,result.text
        assert calls==[old['job_id']] and port.creates==2
        assert workflow.read_execution()['job_id']==new['job_id']
        assert (workflow.job_directory(old['job_id'])/'drawing_plan.json').read_bytes()==old_plan
    asyncio.run(client_run(check))
