"""통합 UI → ROS 서비스 → 실제 제어 세션을 사용하는 시험 프로세스의 왕복 검증."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import httpx
import pytest


def test_ui_pause_resume_force_reset_over_ros_and_process(monkeypatch,tmp_path):
    if os.environ.get('ROS_DOMAIN_ID')!='99':pytest.skip('실물과 분리된 도메인 99가 필요합니다.')
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from art_artwork_pipeline.standalone_drawer import StandaloneDrawerNode
    from art_artwork_pipeline.path_planner.drawing_plan import build_plan,write_job_plan
    from art_kiosk_bridge.bridge_node import KioskBridgeNode
    from art_kiosk_bridge.http_api import create_app
    from art_kiosk import server,workflow
    monkeypatch.setenv('ART_JOB_PLAN_ROOT',str(tmp_path))
    settings=tmp_path/'control.json';settings.write_text(json.dumps(dict(validated=True,force_limits=[10.]*6,force_bias=[0.]*6)))
    monkeypatch.setenv('ART_MOTION_CONTROL_CONFIG',str(settings))
    monkeypatch.setenv('ART_STANDALONE_SCRIPT',str(Path(__file__).parents[1]/'robot_worker_fixture.py'))
    monkeypatch.setenv('ART_WS_DSR_SETUP','')
    force=tmp_path/'force';monkeypatch.setenv('A4_TEST_FORCE_FLAG',str(force))
    gate=tmp_path/'motion_gate';gate.touch();monkeypatch.setenv('A4_TEST_MOTION_GATE',str(gate))
    plan=build_plan([dict(points=[[0,0],[10,0]]),dict(points=[[10,10],[100,10]])],110,30,job_id='UI_PROCESS',paper_size_mm=(297.,210.))
    path=Path(write_job_plan(plan,tmp_path));job=plan['job_id']
    (path.parent/'job_metadata.json').write_text(json.dumps(dict(job_id=job,approved=False)))
    workflow.save_state(dict(version=1,job_id=job,phase='PREVIEW',ticket='TICKET',text='',sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    rclpy.init();backend=StandaloneDrawerNode();bridge=KioskBridgeNode();executor=MultiThreadedExecutor(num_threads=6)
    for node in (backend,bridge):executor.add_node(node)
    worker=threading.Thread(target=executor.spin,daemon=True);worker.start()
    monkeypatch.setattr(server.app.state,'bridge_transport',httpx.ASGITransport(app=create_app(bridge)),raising=False)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://test') as client:
            deadline=time.monotonic()+6
            while not bridge.is_ready() and time.monotonic()<deadline:await asyncio.sleep(.02)
            assert bridge.is_ready()
            response=await client.post('/api/kiosk/draw',json={'ticket':'TICKET'});assert response.status_code==202,response.text
            async def observed(predicate):
                end=time.monotonic()+10
                while time.monotonic()<end:
                    snapshot=(await client.get('/api/kiosk/current')).json().get('status')
                    if snapshot and predicate(snapshot):return snapshot
                    await asyncio.sleep(.01)
                raise AssertionError(str(backend._status))
            async def control(command,key):
                return await client.post('/api/kiosk/current/control',json=dict(expected_job_id=job,command=command,request_id=key))
            await observed(lambda s:s['state']=='DRAWING' and s['completed_length_mm']>0)
            assert (await control('PAUSE','P')).status_code==202
            paused=await observed(lambda s:s['state']=='PAUSED');assert 0<paused['completed_length_mm']<paused['total_length_mm']
            gate.touch()
            assert (await control('RESUME','R')).status_code==202
            await observed(lambda s:s['state']=='DRAWING')
            force.touch();forced=await observed(lambda s:s['state']=='FORCE_STOPPED');assert forced['external_force']
            assert (await control('RESUME','NOT_READY')).status_code==202
            await observed(lambda s:s.get('control_error')=='RESUME_NOT_READY')
            force.unlink();gate.unlink();assert (await control('RESUME','RESUME_AFTER_FORCE')).status_code==202
            completed=await observed(lambda s:s['state']=='COMPLETED')
            assert completed['completed_length_mm']==completed['total_length_mm']
            assert completed['run_id']==1
            from art_artwork_pipeline.recovery_store import CheckpointStore
            assert CheckpointStore().latest() is None
    try:asyncio.run(run())
    finally:
        backend.stop_worker();executor.shutdown(timeout_sec=5);worker.join(5)
        bridge.destroy_node();backend.destroy_node();rclpy.shutdown()
