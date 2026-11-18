"""두산 비동기 경로의 중간 정지·재개. 실물 검증 전에는 실행 경로에 자동 연결하지 않습니다."""
from dataclasses import dataclass
import math
import threading
import time

@dataclass(frozen=True)
class HoldSnapshot:
    pose: tuple
    pending_motion: bool

class DoosanMotionControl:
    """팀원의 활성 Controller Node에 연결합니다. 별도 Executor 스레드가 필요합니다.

    ready는 TCP/보정/파지/장비 상태를 검증하는 함수입니다.
    stop_and_lift는 모션 정지 후 안전 이격을 실제 관측하고 bool을 반환해야 합니다.
    이 두 필수 연결이 없으면 생성할 수 없습니다. 필압·그리퍼 출력은 여기서 변경하지 않습니다.
    """
    def __init__(self, node, *, ready, stop_and_lift, motion_complete, prefix='/dsr01/dsr_controller2',
                 timeout=3., linear_tolerance_mm=.1, angular_tolerance_deg=.1):
        if not callable(ready) or not callable(stop_and_lift) or not callable(motion_complete):
            raise ValueError('장비 준비와 정지·이격 검증 함수가 필요합니다.')
        if not all(math.isfinite(v) and v>0 for v in (timeout,linear_tolerance_mm,angular_tolerance_deg)):
            raise ValueError('유효한 확인 시간과 위치 허용치가 필요합니다.')
        from dsr_msgs2.srv import MovePause, MoveResume, MoveStop, CheckMotion, GetRobotState, GetCurrentPosx, GetCurrentVelx
        from rclpy.callback_groups import ReentrantCallbackGroup
        self.ready,self.stop_and_lift=ready,stop_and_lift
        self.motion_complete=motion_complete
        self.timeout=timeout
        self.linear_tolerance,self.angular_tolerance=linear_tolerance_mm,angular_tolerance_deg
        self.types=dict(pause=MovePause,resume=MoveResume,stop=MoveStop,motion=CheckMotion,
                        state=GetRobotState,pose=GetCurrentPosx,velocity=GetCurrentVelx)
        suffixes=dict(pause='motion/move_pause',resume='motion/move_resume',stop='motion/move_stop',
                      motion='motion/check_motion',state='system/get_robot_state',
                      pose='aux_control/get_current_posx',velocity='aux_control/get_current_velx')
        self.clients={k:node.create_client(self.types[k], prefix.rstrip('/')+'/'+path,
                     callback_group=ReentrantCallbackGroup()) for k,path in suffixes.items()}

    def call(self, key, deadline, **fields):
        remaining=deadline-time.monotonic()
        client=self.clients[key]
        if remaining<=0 or not client.service_is_ready():
            raise RuntimeError('DRIVER_UNAVAILABLE_OR_TIMEOUT')
        future=client.call_async(self.types[key].Request(**fields))
        done=threading.Event()
        future.add_done_callback(lambda _:done.set())
        if not done.wait(max(0.,deadline-time.monotonic())):
            raise RuntimeError('DRIVER_RESPONSE_UNKNOWN')
        result=future.result()
        if result is None or not result.success:
            raise RuntimeError('DRIVER_REJECTED_'+key.upper())
        return result

    def observed(self, deadline):
        if self.ready() is not True:
            raise RuntimeError('EQUIPMENT_NOT_READY')
        state=int(self.call('state',deadline).robot_state)
        if state not in (1,2):
            raise RuntimeError('ROBOT_STATE_BLOCKED')
        info=self.call('pose',deadline,ref=0).task_pos_info
        pose=tuple(info[0].data[:6]) if info else ()
        velocity=tuple(self.call('velocity',deadline,ref=0).vel)
        if len(pose)!=6 or len(velocity)!=6 or not all(math.isfinite(v) for v in pose+velocity):
            raise RuntimeError('INVALID_OBSERVATION')
        return pose,velocity

    def stationary(self, deadline):
        previous=None
        for _ in range(3):
            pose,velocity=self.observed(deadline)
            if any(abs(v)>.01 for v in velocity):
                raise RuntimeError('MOTION_NOT_STATIONARY')
            if previous is not None and not self.same_pose(previous,pose):
                raise RuntimeError('HOLD_POSE_CHANGED')
            previous=pose
            time.sleep(.02)
        return pose

    def same_pose(self,a,b):
        # 같은 자세 표현을 요구합니다. 다른 오일러 표현은 자동 동등 처리하지 않고 거절합니다.
        return (math.dist(a[:3],b[:3])<=self.linear_tolerance
                and max(abs(x-y) for x,y in zip(a[3:],b[3:]))<=self.angular_tolerance)

    def pause(self, inflight):
        deadline=time.monotonic()+self.timeout
        self.observed(deadline)
        while True:
            status=int(self.call('motion',deadline).status)
            if status not in (0,1,2):
                raise RuntimeError('UNKNOWN_MOTION_STATE')
            if not inflight or status in (1,2) or self.motion_complete() is True:
                break
            if time.monotonic()>=deadline:
                raise RuntimeError('PATH_CONTEXT_LOST')
            time.sleep(.02)
        pending=inflight and status in (1,2)
        if pending:
            self.call('pause',deadline)
        # 서비스 수락 직후 감속이 끝날 때까지 전체 deadline 안에서 관측합니다.
        while True:
            try:
                pose=self.stationary(deadline)
                return HoldSnapshot(pose,bool(pending))
            except RuntimeError as exc:
                if str(exc) not in ('MOTION_NOT_STATIONARY','HOLD_POSE_CHANGED') or time.monotonic()>=deadline:
                    raise
                time.sleep(.02)

    def resume(self, hold, inflight):
        if not isinstance(hold,HoldSnapshot):
            raise RuntimeError('NO_RETAINED_PATH')
        deadline=time.monotonic()+self.timeout
        pose=self.stationary(deadline)
        if not self.same_pose(hold.pose,pose):
            raise RuntimeError('PAUSED_POSE_CHANGED')
        if hold.pending_motion:
            if not inflight:
                raise RuntimeError('PATH_CONTEXT_LOST')
            self.call('resume',deadline)
            # 수락 응답만으로 DRAWING을 표시하지 않습니다. 실제 속도 또는
            # 생산자가 보유한 동일 목표의 도달 확인이 있어야 재개를 확정합니다.
            while True:
                _,velocity=self.observed(deadline)
                if any(abs(v)>.01 for v in velocity) or self.motion_complete() is True:
                    return
                if time.monotonic()>=deadline:
                    raise RuntimeError('RESUME_UNCONFIRMED')
                time.sleep(.02)

    def stop(self):
        deadline=time.monotonic()+self.timeout
        self.call('stop',deadline,stop_mode=2)
        while True:
            status=int(self.call('motion',deadline).status)
            if status==0:
                break
            if time.monotonic()>=deadline:
                raise RuntimeError('STOP_UNCONFIRMED')
            time.sleep(.02)
        self.stationary(deadline)
        # IDLE만으로 펜 이격을 꾸며내지 않습니다.
        return self.stop_and_lift() is True
