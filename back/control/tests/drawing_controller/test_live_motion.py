"""중간 모션 보존·중복 명령·취소 경합을 로봇 없이 검증합니다."""
import threading
import time
import pytest
from art_drawing_controller.live_motion import LiveMotionSession
from art_drawing_controller.doosan_motion_control import DoosanMotionControl, HoldSnapshot

class Adapter:
    def __init__(self):
        self.calls=[]
        self.position=3
    def pause(self,inflight):
        self.calls.append(('pause',inflight))
        return self.position
    def resume(self,hold,inflight):
        self.calls.append(('resume',inflight))
        if hold != self.position:
            raise RuntimeError('POSITION_CHANGED')
    def stop(self):
        self.calls.append(('stop',))
        return True

def session(adapter=None):
    return LiveMotionSession('J1','abc',adapter or Adapter(),lambda event:None)

def test_partial_motion_is_retained_not_resubmitted():
    item=session();submitted=[]
    item.submit_motion(lambda:submitted.append('original-target'))
    assert item.control('abc','PAUSE','p1')==(True,'PAUSED','')
    assert item.control('abc','PAUSE','p1')==(True,'PAUSED','')
    assert item.inflight and not item.complete_motion()
    with pytest.raises(RuntimeError):item.submit_motion(lambda:submitted.append('new-target'))
    assert item.control('abc','RESUME','r1')==(True,'DRAWING','')
    assert item.inflight and submitted==['original-target']
    assert item.adapter.calls==[('pause',True),('resume',True)]
    assert item.control('abc','PAUSE','p1')[2]=='STALE_CONTROL_RECEIPT'
    assert item.state=='RUNNING'
    assert item.complete_motion() and item.finish()
    assert item.control('abc','PAUSE','new')[0] is False

def test_wrong_execution_conflict_and_pose_change():
    item=session();item.submit_motion(lambda:None)
    assert not item.control('old','PAUSE','p')[0]
    assert item.control('abc','PAUSE','p')[0]
    assert item.control('abc','RESUME','p')[2]=='REQUEST_ID_CONFLICT'
    item.adapter.position=9
    assert not item.control('abc','RESUME','r')[0]
    assert item.state=='FAILED'

def test_cancel_paused_requires_real_stop_confirmation():
    item=session();item.submit_motion(lambda:None)
    item.control('abc','PAUSE','p')
    item.adapter.stop=lambda:False
    assert not item.cancel() and item.state=='FAILED'
    assert not item.control('abc','RESUME','r')[0]

def test_cancel_during_resume_never_reopens_producer():
    entered,release=threading.Event(),threading.Event()
    adapter=Adapter()
    def resume(hold,inflight):
        entered.set();assert release.wait(2)
    adapter.resume=resume
    item=session(adapter);item.submit_motion(lambda:None);item.control('abc','PAUSE','p')
    worker=threading.Thread(target=lambda:item.control('abc','RESUME','r'))
    worker.start();assert entered.wait(1)
    canceller=threading.Thread(target=item.cancel);canceller.start()
    deadline=time.monotonic()+1
    while item.state!='STOPPING' and time.monotonic()<deadline:time.sleep(.001)
    assert item.state=='STOPPING'
    release.set();worker.join(2);canceller.join(2)
    assert item.state=='STOPPED' and not item.wait_running(0)
    assert adapter.calls[-1]==('stop',)

class ObservedDriver(DoosanMotionControl):
    """드라이버 관측값만 대체하고 실제 어댑터 로직을 실행합니다."""
    def __init__(self):
        self.ready=lambda:True;self.stop_and_lift=lambda:True;self.motion_complete=lambda:False
        self.timeout=.5;self.linear_tolerance=.1;self.angular_tolerance=.1
        self.pose=(10.,20.,30.,0.,90.,0.);self.velocity=(0.,)*6;self.robot_state=1
        self.calls=[];self.motion=2
    def call(self,key,deadline,**fields):
        from types import SimpleNamespace as R
        self.calls.append(key)
        if key=='state':return R(robot_state=self.robot_state)
        if key=='pose':return R(task_pos_info=[R(data=self.pose)])
        if key=='velocity':return R(vel=self.velocity)
        if key=='motion':return R(status=self.motion)
        if key=='resume':self.velocity=(1.,0.,0.,0.,0.,0.)
        if key=='stop':self.motion=0
        return R(success=True)

def test_doosan_adapter_calls_pause_resume_without_new_motion_or_pen_output():
    driver=ObservedDriver()
    hold=driver.pause(True)
    assert hold==HoldSnapshot(driver.pose,True)
    driver.resume(hold,True)
    assert driver.calls.count('pause')==driver.calls.count('resume')==1
    assert set(driver.calls)<=set(('state','pose','velocity','motion','pause','resume'))

def test_doosan_adapter_refuses_changed_pose_and_emergency_state():
    driver=ObservedDriver();hold=driver.pause(True)
    driver.pose=(20.,20.,30.,0.,90.,0.)
    with pytest.raises(RuntimeError,match='PAUSED_POSE_CHANGED'):driver.resume(hold,True)
    assert 'resume' not in driver.calls
    driver.robot_state=6
    with pytest.raises(RuntimeError,match='ROBOT_STATE_BLOCKED'):driver.resume(hold,True)
    assert 'resume' not in driver.calls

def test_no_pending_motion_at_boundary_does_not_call_move_resume():
    driver=ObservedDriver();driver.motion=0
    hold=driver.pause(False);driver.resume(hold,False)
    assert 'pause' not in driver.calls and 'resume' not in driver.calls
