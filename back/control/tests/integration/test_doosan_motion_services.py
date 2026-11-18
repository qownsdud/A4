"""실제 dsr_msgs2 타입으로 가짜 두산 서비스와 어댑터를 연결합니다. 장비는 사용하지 않습니다."""
import os
import threading
import time
import pytest
rclpy=pytest.importorskip('rclpy')
pytest.importorskip('dsr_msgs2.srv',reason='로컬 두산 워크스페이스 overlay가 필요합니다.')
from dsr_msgs2.srv import MovePause,MoveResume,MoveStop,CheckMotion,GetRobotState,GetCurrentPosx,GetCurrentVelx
from std_msgs.msg import Float64MultiArray
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from art_drawing_controller.doosan_motion_control import DoosanMotionControl


def test_doosan_pause_resume_and_stop_use_actual_service_types():
    if os.environ.get('ROS_DOMAIN_ID') not in ('97','99'):
        pytest.skip('격리 도메인이 필요합니다.')
    rclpy.init();driver=Node('fake_dsr_service_test');client=Node('dsr_adapter_test')
    # 실제 드라이버의 고정 경로와 겹치지 않는 시험 전용 prefix입니다.
    prefix='/a4_fake_dsr_test'
    state={'paused':False,'moving':True,'calls':[]}
    pose=[100.,200.,300.,0.,90.,0.]
    def pause(req,res):state['paused']=True;state['calls'].append('pause');res.success=True;return res
    def resume(req,res):state['paused']=False;state['calls'].append('resume');res.success=True;return res
    def stop(req,res):
        assert req.stop_mode==2
        state['moving']=False;state['calls'].append('stop');res.success=True;return res
    def motion(req,res):res.status=2 if state['moving'] else 0;res.success=True;return res
    def robot(req,res):res.robot_state=1;res.success=True;return res
    def position(req,res):res.task_pos_info=[Float64MultiArray(data=pose+[0.])];res.success=True;return res
    def velocity(req,res):
        res.vel=[1. if state['moving'] and not state['paused'] else 0.]+[0.]*5
        res.success=True;return res
    for typ,path,callback in ((MovePause,'motion/move_pause',pause),(MoveResume,'motion/move_resume',resume),
        (MoveStop,'motion/move_stop',stop),(CheckMotion,'motion/check_motion',motion),
        (GetRobotState,'system/get_robot_state',robot),(GetCurrentPosx,'aux_control/get_current_posx',position),
        (GetCurrentVelx,'aux_control/get_current_velx',velocity)):
        driver.create_service(typ,prefix+'/'+path,callback)
    lifted=[]
    adapter=DoosanMotionControl(client,ready=lambda:True,stop_and_lift=lambda:lifted.append('verified') or True,
                                motion_complete=lambda:False,prefix=prefix)
    executor=MultiThreadedExecutor(num_threads=4)
    executor.add_node(driver);executor.add_node(client)
    worker=threading.Thread(target=executor.spin,daemon=True);worker.start()
    try:
        deadline=time.monotonic()+5
        while not all(c.service_is_ready() for c in adapter.clients.values()) and time.monotonic()<deadline:time.sleep(.01)
        hold=adapter.pause(True)
        assert hold.pending_motion and state['paused']
        adapter.resume(hold,True)
        assert not state['paused'] and not lifted
        assert adapter.stop() is True
        assert state['calls']==['pause','resume','stop'] and lifted==['verified']
    finally:
        executor.shutdown(timeout_sec=3);worker.join(3)
        driver.destroy_node();client.destroy_node();rclpy.shutdown()
