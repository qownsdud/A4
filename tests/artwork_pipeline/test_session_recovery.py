"""실제 ROS 관측 서비스와 세션 정리의 왕복 검증. 시험 도메인에서만 실행합니다."""

import os
import threading
from pathlib import Path
import pytest


def test_reconcile_uses_real_ros_observations_and_rejects_motion(monkeypatch,tmp_path):
    if os.environ.get('ROS_DOMAIN_ID')!='99':pytest.skip('격리 도메인 99가 필요합니다.')
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from dsr_msgs2.srv import GetRobotState, CheckMotion, GetCurrentPosx, GetCurrentVelx
    from std_msgs.msg import Float64MultiArray
    from art_interfaces.srv import ControlJob
    from art_artwork_pipeline.standalone_drawer import StandaloneDrawerNode
    from art_artwork_pipeline.path_planner.drawing_plan import build_plan,write_job_plan
    monkeypatch.setenv('ART_JOB_PLAN_ROOT',str(tmp_path))
    plan=build_plan([dict(points=[[0,0],[10,10]])],20,20,job_id='RECOVER')
    write_job_plan(plan,tmp_path)
    rclpy.init();node=StandaloneDrawerNode();driver=rclpy.create_node('fake_recovery_observer')
    moving={'value':True}
    def state(req,res):res.robot_state=2 if moving['value'] else 1;res.success=True;return res
    def motion(req,res):res.status=2 if moving['value'] else 0;res.success=True;return res
    def pose(req,res):res.task_pos_info=[Float64MultiArray(data=[0.]*7)];res.success=True;return res
    def velocity(req,res):res.vel=[0.]*6;res.success=True;return res
    services=[]
    for kind,suffix,callback in ((GetRobotState,'system/get_robot_state',state),(CheckMotion,'motion/check_motion',motion),(GetCurrentPosx,'aux_control/get_current_posx',pose),(GetCurrentVelx,'aux_control/get_current_velx',velocity)):
        services.append(driver.create_service(kind,'/dsr01/dsr_controller2/'+suffix,callback))
    executor=MultiThreadedExecutor(num_threads=6)
    executor.add_node(node);executor.add_node(driver)
    worker=threading.Thread(target=executor.spin,daemon=True);worker.start()
    try:
        request=ControlJob.Request(job_id='RECOVER',command='RECONCILE',request_id='CHECK')
        # 실행 명령 경로를 호출하되 관측 서비스만 제공하여 이동 호출이 없음을 확인합니다.
        response=node._on_control_job(request,ControlJob.Response())
        assert not response.accepted and response.error_code=='RECONCILE_REFUSED'
        assert node._status is None
        moving['value']=False
        response=node._on_control_job(request,ControlJob.Response())
        assert response.accepted and response.state=='STOPPED'
        assert node._status['completed_strokes']==0 and node._status['completed_length_mm']==0.
        assert '정지' in node._status['message']
        # 살아 있는 실행기는 실제 정지 수치가 0이어도 정리하지 않습니다.
        class Process:
            def poll(self):return None
        node._proc=Process()
        response=node._on_control_job(request,ControlJob.Response())
        assert not response.accepted and response.error_code=='EXECUTION_STILL_ACTIVE'
        node._proc=None
    finally:
        executor.shutdown(timeout_sec=5);worker.join(5)
        node.destroy_node();driver.destroy_node();rclpy.shutdown()


def test_ui_bridge_ros_recovery_then_new_drawing_survives_web_reload(monkeypatch,tmp_path):
    """웹→Bridge→ROS 정지 관측→기록 복구→새 가짜 드로잉의 전체 경로입니다."""
    if os.environ.get('ROS_DOMAIN_ID')!='99':pytest.skip('격리 도메인 99가 필요합니다.')
    import asyncio
    import hashlib
    import importlib
    import json
    import rclpy
    import httpx
    from rclpy.executors import MultiThreadedExecutor
    from dsr_msgs2.srv import GetRobotState,CheckMotion,GetCurrentPosx,GetCurrentVelx
    from std_msgs.msg import Float64MultiArray
    from art_artwork_pipeline.standalone_drawer import StandaloneDrawerNode
    from art_artwork_pipeline.path_planner.drawing_plan import build_plan,write_job_plan
    from art_kiosk_bridge.bridge_node import KioskBridgeNode
    from art_kiosk_bridge.http_api import create_app
    from art_kiosk import server,workflow
    from art_artwork_pipeline.pipeline_runner import atomic_json
    monkeypatch.setenv('ART_JOB_PLAN_ROOT',str(tmp_path))
    monkeypatch.setenv('ART_STANDALONE_SCRIPT',str(Path(__file__).parents[1]/'robot_worker_fixture.py'))
    monkeypatch.setenv('ART_WS_DSR_SETUP','')
    settings=tmp_path/'settings.json'
    settings.write_text(json.dumps(dict(validated=True,force_limits=[10.]*6,force_bias=[0.]*6)))
    monkeypatch.setenv('ART_MOTION_CONTROL_CONFIG',str(settings))
    paths={}
    for job in ('OLD_SESSION','NEW_PREVIEW'):
        plan=build_plan([dict(points=[[0,0],[10,10]])],20,20,job_id=job)
        paths[job]=Path(write_job_plan(plan,tmp_path))
        (paths[job].parent/'job_metadata.json').write_text(json.dumps(dict(job_id=job,approved=False)))
    old=dict(version=1,job_id='OLD_SESSION',phase='REGISTERED',ticket='OLD',text='Old')
    atomic_json(workflow.execution_path(),old)
    workflow.save_state(dict(version=1,job_id='NEW_PREVIEW',phase='PREVIEW',ticket='NEW',text='New',
                             sha256=hashlib.sha256(paths['NEW_PREVIEW'].read_bytes()).hexdigest()))
    rclpy.init();backend=StandaloneDrawerNode();bridge=KioskBridgeNode();driver=rclpy.create_node('session_observation_fixture')
    def state(req,res):res.robot_state=1;res.success=True;return res
    def motion(req,res):res.status=0;res.success=True;return res
    def pose(req,res):res.task_pos_info=[Float64MultiArray(data=[0.]*7)];res.success=True;return res
    def velocity(req,res):res.vel=[0.]*6;res.success=True;return res
    services=[]
    for kind,suffix,callback in ((GetRobotState,'system/get_robot_state',state),(CheckMotion,'motion/check_motion',motion),(GetCurrentPosx,'aux_control/get_current_posx',pose),(GetCurrentVelx,'aux_control/get_current_velx',velocity)):
        services.append(driver.create_service(kind,'/dsr01/dsr_controller2/'+suffix,callback))
    executor=MultiThreadedExecutor(num_threads=6)
    for node in (backend,bridge,driver):executor.add_node(node)
    worker=threading.Thread(target=executor.spin,daemon=True);worker.start()
    monkeypatch.setattr(server.app.state,'bridge_transport',httpx.ASGITransport(app=create_app(bridge)),raising=False)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://test') as client:
            import time
            end=time.monotonic()+6
            while not bridge.is_ready() and time.monotonic()<end:await asyncio.sleep(.02)
            assert bridge.is_ready()
            before=(await client.get('/api/kiosk/current')).json()
            assert before['can_draw']
            response=await client.post('/api/kiosk/recover-execution',json=dict(expected_job_id='OLD_SESSION',request_id='RECOVERY',operator_confirmed_stopped=True))
            assert response.status_code==200,response.text
            assert workflow.read_state()['job_id']=='NEW_PREVIEW'
            # 웹 상태를 다시 읽어도 완료 확인은 유지되고, 도안을 자동 실행하지 않습니다.
            importlib.reload(workflow)
            after=(await client.get('/api/kiosk/current')).json()
            assert after['can_draw'] and not after['can_recover']
            assert backend._status['job_id']=='OLD_SESSION' and backend._proc is None
            response=await client.post('/api/kiosk/draw',json=dict(ticket='NEW'))
            assert response.status_code==202,response.text
            end=time.monotonic()+8
            while time.monotonic()<end:
                snapshot=(await client.get('/api/kiosk/current')).json()['status']
                if snapshot and snapshot['job_id']=='NEW_PREVIEW' and snapshot['state']=='COMPLETED':return
                await asyncio.sleep(.02)
            pytest.fail(str(backend._status))
    try:asyncio.run(run())
    finally:
        backend.stop_worker();executor.shutdown(timeout_sec=5);worker.join(5)
        for node in (backend,bridge,driver):node.destroy_node()
        rclpy.shutdown()


def test_native_node_recovers_checkpoint_after_restart_without_auto_motion(monkeypatch,tmp_path):
    import hashlib,json
    import rclpy
    from art_artwork_pipeline.standalone_drawer import StandaloneDrawerNode
    from art_artwork_pipeline.recovery_store import RecoveryJournal,CheckpointStore
    from art_artwork_pipeline.path_planner.drawing_plan import build_plan,write_job_plan
    from art_interfaces.srv import ControlJob
    monkeypatch.setenv('ART_JOB_PLAN_ROOT',str(tmp_path))
    settings=tmp_path/'control.json';settings.write_text(json.dumps(dict(validated=True,force_limits=[10.]*6,force_bias=[0.]*6)))
    monkeypatch.setenv('ART_MOTION_CONTROL_CONFIG',str(settings))
    plan=build_plan([dict(points=[[0,0],[10,10]])],20,20,job_id='DURABLE_NODE')
    path=Path(write_job_plan(plan,tmp_path));sha=hashlib.sha256(path.read_bytes()).hexdigest()
    journal=RecoveryJournal('DURABLE_NODE',path,sha)
    journal.runtime=dict(held_pen_id='PEN_1',phase='drawing')
    journal.sample(target_pose=[10.,10.,0.,0.,0.,0.],actual_pose=[2.,2.,0.,0.,0.,0.],force=[0.]*6,
        waypoint=dict(stroke_id=1,point_index=1,pen_id='PEN_1',return_pose=[0.]*6,base_length_mm=0.),
        completed_strokes=0,completed_length_mm=2.,runtime=journal.runtime)
    journal.interrupt('FORCE',[3.,4.,0.,0.,0.,0.],stop_confirmed=True)
    checkpoint=CheckpointStore().latest();del journal
    rclpy.init();node=StandaloneDrawerNode()
    try:
        assert node._status['state']=='RECOVERY_REQUIRED' and node._proc is None
        observed=[];commands=[]
        monkeypatch.setattr(node,'_observe_idle',lambda:observed.append('stationary'))
        monkeypatch.setattr(node,'_run_standalone',lambda job,path:commands.append(node._build_command(path)))
        response=node._on_control_job(ControlJob.Request(job_id='DURABLE_NODE',command='RESUME',request_id='R'),ControlJob.Response())
        assert response.accepted,response.message
        node._worker.join(2)
        assert observed==['stationary'] and len(commands)==1
        command=' '.join(commands[0])
        assert '--resume-checkpoint' in command and checkpoint['checkpoint_id'] in command
        assert hashlib.sha256(path.read_bytes()).hexdigest()==sha
    finally:node.destroy_node();rclpy.shutdown()


def test_corrupt_checkpoint_database_blocks_new_native_goal(monkeypatch,tmp_path):
    import rclpy
    from art_artwork_pipeline.standalone_drawer import StandaloneDrawerNode
    from art_interfaces.srv import CreateJob
    database=tmp_path/'broken.sqlite3';database.write_bytes(b'broken')
    monkeypatch.setenv('ART_RECOVERY_DB',str(database))
    rclpy.init();node=StandaloneDrawerNode()
    try:
        response=node._on_create_job(CreateJob.Request(job_id='NEW',plan_path='/missing'),CreateJob.Response())
        assert not response.accepted and '중단점 저장소' in response.message
        assert node._proc is None
    finally:node.destroy_node();rclpy.shutdown()


def test_replace_retry_uses_new_internal_cancel_attempt(monkeypatch,tmp_path):
    import rclpy
    from art_artwork_pipeline.standalone_drawer import StandaloneDrawerNode
    from art_interfaces.srv import ControlJob
    monkeypatch.setenv('ART_JOB_PLAN_ROOT',str(tmp_path))
    rclpy.init();node=StandaloneDrawerNode()
    class ActiveProcess:
        def poll(self):return None
    node._proc=ActiveProcess()
    attempts=[]
    def denied(command,key):
        attempts.append((command,key))
        raise RuntimeError('시험: 외력 해소 전 정리 거절')
    monkeypatch.setattr(node,'_send',denied)
    request=ControlJob.Request(job_id='OLD',command='REPLACE',request_id='SAME_NEW_PLAN')
    try:
        for _ in range(2):
            reply=node._on_control_job(request,ControlJob.Response())
            assert not reply.accepted
        assert len(attempts)==2 and attempts[0][0]==attempts[1][0]=='CANCEL'
        assert attempts[0][1]!=attempts[1][1] and all(len(key)<=64 for cmd,key in attempts)
    finally:
        node._proc=None;node.destroy_node();rclpy.shutdown()
