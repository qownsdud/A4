# [파일 역할] Controller Action Server 가짜 구현 (시험 전용)
# [동작] /art/execute_drawing Action 요청을 받아 가상으로 STARTED/STROKE_STARTED/STROKE_COMPLETED를 발행합니다.
# [주의] 로봇과 절대 연결하지 마세요. 별도의 테스트 ROS_DOMAIN_ID에서만 실행하세요.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""TEST-ONLY /art/execute_drawing ActionServer. NEVER controls M0609/RG2.

Run only in an isolated simulation DDS domain; DO NOT run while a real robot
controller uses /art/execute_drawing.
TEAM_SYNC(Robot): this is a contract emulator, not the actual controller.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from art_interfaces.action import ExecuteDrawing
from art_drawing_controller.live_motion import LiveMotionSession
from art_drawing_controller.live_control_server import LiveControlServer


class FakeController(Node):
    def __init__(self):
        super().__init__('fake_drawing_controller_test_only')
        self._busy = False
        self.live_control = LiveControlServer(self)
        self.sessions = []
        self.samples = []
        self.goal_count = 0
        self._delay = float(os.environ.get('A4_FAKE_STROKE_SECONDS', '0.25'))
        self.server = ActionServer(
            self, ExecuteDrawing, '/art/execute_drawing',
            execute_callback=self._execute,
            goal_callback=self._goal,
            cancel_callback=self._cancel,
            callback_group=ReentrantCallbackGroup(),
        )
        self.get_logger().warning('FAKE CONTROLLER ONLY: does not touch any robot')

    # [핵심 기능] 시험용 Controller가 새 Goal을 수락할지 결정
    def _goal(self, request):
        if self._busy:
            return GoalResponse.REJECT
        self._busy = True
        self.goal_count += 1
        return GoalResponse.ACCEPT

    @staticmethod
    # [핵심 기능] 시험용 Controller에서 Action 취소 요청 수락
    def _cancel(_goal_handle):
        return CancelResponse.ACCEPT

    # [핵심 기능] 시험용 획 이벤트를 ROS Action Feedback으로 발행
    def _feedback(self, goal_handle, event: str, stroke_id: int = 0,
                  pen_id: str = '', pen_up: bool = False):
        fb = ExecuteDrawing.Feedback()
        fb.event = event
        fb.stroke_id = stroke_id
        fb.pen_id = pen_id
        fb.pen_up_confirmed = pen_up
        fb.message = 'FAKE CONTROLLER — no physical motion'
        goal_handle.publish_feedback(fb)

    # [핵심 기능] 시험용 가짜 획 진행 후 ROS Action Result 반환
    def _execute(self, handle):
        result = ExecuteDrawing.Result()
        result.success = False
        result.final_state = 'FAILED'
        result.error_code = ''
        result.message = 'FAKE CONTROLLER only'
        completed = handle.request.start_stroke_id - 1
        result.completed_strokes = completed
        result.pen_up_confirmed = True
        session = None
        try:
            plan_path = Path(handle.request.plan_path)
            payload = plan_path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != handle.request.plan_sha256:
                result.error_code = 'PLAN_SHA256_MISMATCH'
                handle.abort()
                return result
            plan = json.loads(payload)
            if plan['job_id'] != handle.request.job_id or not 1 <= handle.request.start_stroke_id <= len(plan['strokes']):
                result.error_code = 'BAD_GOAL'
                handle.abort()
                return result
            # 시험 전용 어댑터입니다. 실제 로봇 상태를 반환하지 않습니다.
            class FakeMotion:
                def pause(inner, inflight):
                    return len(self.samples)
                def resume(inner, hold, inflight):
                    if hold != len(self.samples):
                        raise RuntimeError('FAKE_PAUSED_PATH_CHANGED')
                def stop(inner):
                    return True
            session = LiveMotionSession(handle.request.job_id, bytes(handle.goal_id.uuid).hex(),
                FakeMotion(), lambda event: self._feedback(handle,event))
            self.sessions.append(session)
            self.live_control.bind(session)
            self._feedback(handle, 'STARTED_LIVE')
            for stroke in plan['strokes'][handle.request.start_stroke_id - 1:]:
                while not session.wait_running():
                    if handle.is_cancel_requested:
                        break
                if handle.is_cancel_requested:
                    if not session.cancel():
                        raise RuntimeError('FAKE_STOP_FAILED')
                    result.final_state = 'INTERRUPTED_SAFE'
                    result.completed_strokes = completed
                    result.pen_up_confirmed = True
                    handle.canceled()
                    return result
                sid, pen = stroke['stroke_id'], stroke['pen_id']
                with session.condition:
                    # 경계의 PAUSE와 새 모션 제출 사이도 같은 게이트로 직렬화합니다.
                    if session.state != 'RUNNING':
                        while not session.wait_running():
                            if handle.is_cancel_requested:
                                break
                    if not handle.is_cancel_requested:
                        session.submit_motion(lambda: None)
                        self._feedback(handle, 'STROKE_STARTED', sid, pen)
                for point_index in range(20):
                    while True:
                        if handle.is_cancel_requested:
                            if not session.cancel():
                                raise RuntimeError('FAKE_STOP_FAILED')
                            result.final_state = 'INTERRUPTED_SAFE'
                            result.completed_strokes = completed
                            result.pen_up_confirmed = True
                            handle.canceled()
                            return result
                        with session.condition:
                            if session.state == 'RUNNING':
                                self.samples.append((sid,point_index))
                                break
                            if session.state == 'FAILED':
                                raise RuntimeError('FAKE_SESSION_FAILED')
                        time.sleep(.002)
                    time.sleep(self._delay/20)
                while True:
                    if handle.is_cancel_requested:
                        if not session.cancel():
                            raise RuntimeError('FAKE_STOP_FAILED')
                        result.final_state='INTERRUPTED_SAFE'
                        result.completed_strokes=completed
                        handle.canceled()
                        return result
                    with session.condition:
                        if session.complete_motion():
                            self._feedback(handle,'STROKE_COMPLETED',sid,pen,True)
                            break
                    time.sleep(.002)
                completed = sid
                result.completed_strokes = completed
            # 마지막 완료와 일시정지가 경합해도 정지 상태를 건너뛰지 않습니다.
            while not session.finish():
                if handle.is_cancel_requested:
                    if not session.cancel():
                        raise RuntimeError('FAKE_STOP_FAILED')
                    result.final_state='INTERRUPTED_SAFE'
                    result.completed_strokes=completed
                    handle.canceled()
                    return result
                time.sleep(.002)
            result.success = True
            result.final_state = 'COMPLETED'
            result.pen_up_confirmed = True
            handle.succeed()
            return result
        except Exception as exc:
            result.error_code = 'FAKE_CONTROLLER_ERROR'
            result.message = str(exc)[:250]
            handle.abort()
            return result
        finally:
            if session is not None:
                self.live_control.unbind(session)
            self._busy = False


# [핵심 기능] 실행 진입점: 환경 변수, ROS 초기화, spin 및 종료 처리
    def destroy_node(self):
        # Jazzy의 Node.destroy_node는 ActionServer를 자동 해제하지 않습니다.
        # 재실행 때 이전 서버가 발견되지 않도록 명시적으로 해제합니다.
        if self.server is not None:
            self.server.destroy()
            self.server = None
        return super().destroy_node()


def main():
    if os.environ.get('A4_ENABLE_FAKE_CONTROLLER') != 'YES':
        raise SystemExit('Set A4_ENABLE_FAKE_CONTROLLER=YES. Never run with hardware connected.')
    rclpy.init()
    node = FakeController()
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
