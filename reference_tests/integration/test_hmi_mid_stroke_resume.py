"""HMI HTTP → 실제 Bridge/Manager/Action → 중간 획 Fake 재개를 검증합니다."""
import asyncio
import importlib.util
import os
from pathlib import Path
import threading
import time
import httpx
import pytest
rclpy=pytest.importorskip('rclpy')
pytest.importorskip('art_interfaces.srv')
from rclpy.executors import MultiThreadedExecutor
from art_job_manager.job_manager_node import RealJobManagerNode
from art_kiosk_bridge.bridge_node import KioskBridgeNode
from art_kiosk_bridge.http_api import create_app
from art_artwork_pipeline.path_planner.drawing_plan import build_plan,write_job_plan
from art_kiosk import server,workflow

@pytest.mark.parametrize('end_command',['RESUME','CANCEL','FAIL'])
def test_hmi_pauses_inside_stroke_and_preserves_same_execution(tmp_path,monkeypatch,end_command):
    if os.environ.get('ROS_DOMAIN_ID') not in ('97','99'):
        pytest.skip('격리 ROS_DOMAIN_ID=97 또는 99가 필요합니다.')
    monkeypatch.setenv('ART_JOB_PLAN_ROOT',str(tmp_path))
    monkeypatch.setenv('A4_FAKE_STROKE_SECONDS','1.5')
    spec=importlib.util.spec_from_file_location('midstroke_fake',Path(__file__).parents[1]/'job_manager_v1/fake_drawing_controller.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    rclpy.init()
    manager=RealJobManagerNode(db_path=tmp_path/'jobs.db',plan_root=tmp_path)
    fake=module.FakeController();bridge=KioskBridgeNode()
    executor=MultiThreadedExecutor(num_threads=6)
    for node in (manager,fake,bridge):executor.add_node(node)
    worker=threading.Thread(target=executor.spin,daemon=True);worker.start()
    monkeypatch.setattr(server.app.state,'bridge_transport',httpx.ASGITransport(app=create_app(bridge)),raising=False)
    async def until(predicate,timeout=8):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate():return
            await asyncio.sleep(.01)
        pytest.fail(str(manager.engine.status('MID')))
    async def run():
        await until(lambda:bridge.is_ready() and manager.action_client.server_is_ready())
        plan=build_plan([{'points':[[0,0],[100,100]]}],110,110,job_id='MID')
        path=write_job_plan(plan,tmp_path)
        assert manager.engine.create_job('MID',str(path)).accepted
        workflow.save_state(dict(version=1,ticket='test-preview-ticket',job_id='MID',phase='REGISTERED',text=''))
        await until(lambda:len(fake.samples)>=3 and bridge.get_status('MID') is not None)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://kiosk.test') as client:
            async def command(cmd,rid):
                response=await client.post('/api/admin/current/control',json=dict(
                    expected_job_id='MID',command=cmd,request_id=rid))
                assert response.status_code==202,response.text
                return response.json()
            if end_command=='FAIL':
                def failed_pause(inflight):
                    raise RuntimeError('DRIVER_PAUSE_FAILED')
                fake.sessions[0].adapter.pause=failed_pause
                await command('PAUSE','failed-pause')
                await until(lambda:manager.engine.status('MID')['state']=='RECOVERY_REQUIRED')
                assert manager.engine.status('MID')['completed_strokes']==0
                return
            for iteration in range(2 if end_command=='RESUME' else 1):
                await command('PAUSE','pause'+str(iteration))
                await until(lambda:manager.engine.status('MID')['state']=='PAUSED')
                row=manager.engine.status('MID')
                assert row['completed_strokes']==0 and row['uncertain_stroke']==1
                assert manager._goal_handle is not None and not manager._cancel_requested
                held=list(fake.samples);assert 0<len(held)<20
                await asyncio.sleep(.2)
                assert fake.samples==held
                # 중복 PAUSE는 동일 실행과 정지 위치를 보존합니다.
                await command('PAUSE','pause'+str(iteration))
                assert fake.samples==held
                if end_command=='CANCEL':
                    await command('CANCEL','cancel')
                    await until(lambda:manager.engine.status('MID')['state']=='STOPPED')
                    assert len(fake.sessions)==fake.goal_count==1
                    assert fake.sessions[0].state=='STOPPED'
                    assert fake.samples==held
                    return
                await command('RESUME','resume'+str(iteration))
                await until(lambda:len(fake.samples)>len(held))
                assert fake.samples[:len(held)]==held
                assert fake.goal_count==1
            await until(lambda:manager.engine.status('MID')['state']=='COMPLETED')
            assert fake.samples==[(1,i) for i in range(20)]
            assert len(fake.sessions)==fake.goal_count==1
            assert manager.engine.status('MID')['completed_strokes']==1
    try:asyncio.run(run())
    finally:
        if manager._active_job_id is not None:
            manager.engine.control_job('MID','CANCEL','cleanup')
            manager._request_cancel()
            deadline=time.monotonic()+3
            while (fake._busy or manager._active_job_id is not None) and time.monotonic()<deadline:time.sleep(.01)
        executor.shutdown(timeout_sec=5);worker.join(timeout=5)
        for node in (manager,fake,bridge):
            executor.remove_node(node);node.destroy_node()
        rclpy.shutdown()
