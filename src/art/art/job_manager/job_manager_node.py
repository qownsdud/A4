# [파일 역할] 실제 JobManager ROS 2 노드 (기본 실행)
# [동작] CreateJob/ControlJob Service와 JobStatus Topic을 제공하고 ExecuteDrawing Action Client를 실행합니다.
# [주의] DrawingController Action Server가 없으면 QUEUED로 대기하며 가짜 진행률을 만들지 않습니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""A4 production JobManager ROS 2 services + real DrawingController Action client.

Run with: ros2 run art.job_manager job_manager
Default: NO simulation. Without a compatible /art/execute_drawing Action server,
accepted jobs remain QUEUED and no progress is fabricated.

TEAM_SYNC(Robot): Implement ExecuteDrawing Action server; only trusted observed
feedback proves stroke completion. Cancel must stop motion and lift the pen.
TEAM_SYNC(Backend/UI): CreateJob accepts already validated DrawingPlan path.
TEAM_SYNC(Operations): E-Stop is physical, not this ROS service.
"""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from art.action import ExecuteDrawing
from art.msg import JobStatus
from art.srv import CreateJob, ControlJob

from .production_engine import ProductionEngine


# [핵심 기능] 실제 Controller Action과 통신하는 JobManager의 ROS 인터페이스
class RealJobManagerNode(Node):
    def __init__(self, *, db_path: Path, plan_root: Path,
                 action_name: str = '/art/execute_drawing',
                 feedback_timeout_sec: float = 60.0):
        super().__init__('job_manager_node')
        self.engine = ProductionEngine(db_path, plan_root=plan_root)
        self.action_name = action_name
        self.feedback_timeout_sec = feedback_timeout_sec
        self.action_client = ActionClient(self, ExecuteDrawing, action_name)
        self.status_pub = self.create_publisher(JobStatus, '/art/job_status', 10)
        self.create_srv = self.create_service(CreateJob, '/art/create_job', self._create)
        self.control_srv = self.create_service(ControlJob, '/art/control_job', self._control)
        self.timer = self.create_timer(0.3, self._poll)
        self._active_job_id: str | None = None
        self._goal_handle = None
        self._cancel_requested = False
        self._last_feedback = time.monotonic()
        self._next_warn = 0.0
        if self.engine.recovered_jobs:
            self.get_logger().error('RECOVERY_REQUIRED on startup: ' + ', '.join(self.engine.recovered_jobs))
        self.get_logger().info('REAL mode only. Awaiting DrawingController Action server: ' + action_name)
        self._publish_all()

    # [핵심 기능] 작업의 상태를 JobStatus ROS Topic으로 발행
    def _publish(self, job_id: str) -> None:
        item = self.engine.status(job_id)
        if not item:
            return
        m = JobStatus()
        m.job_id = item['job_id']
        m.state = item['state']
        m.completed_strokes = item['completed_strokes']
        m.total_strokes = item['total_strokes']
        m.current_pen = item['current_pen']
        m.error_code = item['error_code']
        m.message = item['message']
        self.status_pub.publish(m)

    # [핵심 기능] 저장된 작업 상태를 주기적으로 재발행
    def _publish_all(self) -> None:
        for row in self.engine.statuses():
            self._publish(row['job_id'])

    @staticmethod
    def _reply(response, result):
        response.accepted = result.accepted
        response.job_id = result.job_id
        response.state = result.state
        response.error_code = result.error_code
        response.message = result.message
        return response

    # [핵심 기능] CreateJob Service 콜백: 파일 검증·DB 등록 후 결과 회신
    def _create(self, request, response):
        result = self.engine.create_job(request.job_id, request.plan_path)
        self._publish(request.job_id)
        return self._reply(response, result)

    # [핵심 기능] ControlJob Service 콜백: 명령 저장 및 안전한 Action 취소 요청
    def _control(self, request, response):
        result = self.engine.control_job(request.job_id, request.command, request.request_id)
        self._publish(request.job_id)
        if (result.accepted and result.state in ('PAUSING', 'STOPPING')
                and self._active_job_id == request.job_id):
            self._request_cancel()
        return self._reply(response, result)

    # [핵심 기능] 주기적으로 대기 작업을 배차하고 Controller 피드백 시간 초과 감시
    def _poll(self):
        now = time.monotonic()
        # Controller action is required for actual progress. Never simulate.
        if self._active_job_id is None:
            queued = [j for j in self.engine.statuses() if j['state'] == 'QUEUED']
            if queued and self.action_client.wait_for_server(timeout_sec=0.0):
                item = queued[0]
                dispatch = self.engine.prepare_dispatch(item['job_id'])
                self._publish(item['job_id'])
                if dispatch:
                    self._send_goal(dispatch)
            elif queued and now >= self._next_warn:
                self.get_logger().warning('Waiting for DrawingController Action server; NO robot motion')
                self._next_warn = now + 10.0
        else:
            job = self.engine.status(self._active_job_id)
            if job and job['state'] in ('PAUSING', 'STOPPING'):
                self._request_cancel()
            if (job and job['state'] not in ('RECOVERY_REQUIRED', 'COMPLETED', 'STOPPED')
                    and now - self._last_feedback > self.feedback_timeout_sec):
                self.engine.mark_uncertain(self._active_job_id, 'CONTROLLER_FEEDBACK_STALE',
                                           'No trusted controller feedback; actual robot state UNKNOWN')
                self.get_logger().error('Controller heartbeat/feedback stale. Operator must verify physical state.')
                self._publish(self._active_job_id)
                self._request_cancel()  # attempt cancellation; never assume success
        # Late-started Bridge learns current status from repeated publication.
        if not hasattr(self, '_last_snapshot') or now - self._last_snapshot >= 1.0:
            self._last_snapshot = now
            self._publish_all()

    # [핵심 기능] Controller에 DrawingPlan 경로와 SHA 및 시작 획 번호를 Action Goal로 전달
    def _send_goal(self, dispatch):
        self._active_job_id = dispatch.job_id
        self._goal_handle = None
        self._cancel_requested = False
        self._last_feedback = time.monotonic()
        goal = ExecuteDrawing.Goal()
        goal.job_id = dispatch.job_id
        goal.plan_path = dispatch.plan_path
        goal.plan_sha256 = dispatch.plan_sha256
        goal.start_stroke_id = dispatch.start_stroke_id
        try:
            future = self.action_client.send_goal_async(
                goal, feedback_callback=lambda msg, jid=dispatch.job_id: self._on_feedback(jid, msg))
            future.add_done_callback(lambda fut, job_id=dispatch.job_id: self._on_goal_response(job_id, fut))
        except Exception as exc:
            self._fault(dispatch.job_id, 'ACTION_SEND_ERROR', repr(exc))
            self._clear_active(dispatch.job_id)

    # [핵심 기능] Controller의 Action Goal 수락·거부 확인
    def _on_goal_response(self, job_id, future):
        if self._active_job_id != job_id:
            return
        try:
            handle = future.result()
            if handle is None or not handle.accepted:
                self._fault(job_id, 'ACTION_REJECTED', 'Controller rejected goal; verify driver, pen and frame')
                self._clear_active(job_id)
                return
            self._goal_handle = handle
            future2 = handle.get_result_async()
            future2.add_done_callback(lambda fut, jid=job_id: self._on_result(jid, fut))
            state = self.engine.status(job_id)['state']
            if state in ('PAUSING', 'STOPPING', 'RECOVERY_REQUIRED'):
                self._request_cancel()
        except Exception as exc:
            self._fault(job_id, 'ACTION_RESPONSE_ERROR', repr(exc))
            self._clear_active(job_id)

    # [핵심 기능] Controller가 보고한 시작·진행·완료 이벤트를 상태 머신에 반영
    def _on_feedback(self, job_id, message):
        if self._active_job_id != job_id:
            return
        fb = message.feedback
        event = fb.event
        self._last_feedback = time.monotonic()
        if event == 'HEARTBEAT':
            valid = True  # liveness only, never progress/pen safety
        elif event == 'STARTED':
            valid = self.engine.on_controller_started(job_id)
        elif event == 'STROKE_STARTED':
            valid = self.engine.on_stroke_started(job_id, int(fb.stroke_id), fb.pen_id)
        elif event == 'STROKE_COMPLETED':
            valid = self.engine.on_stroke_completed(job_id, int(fb.stroke_id),
                                                     pen_up_confirmed=bool(fb.pen_up_confirmed))
        else:
            valid = False
        if not valid:
            self._fault(job_id, 'INVALID_ACTION_FEEDBACK', f'event={event} stroke={fb.stroke_id}')
            self._request_cancel()
        self._publish(job_id)

    # [핵심 기능] Action 취소 요청 전송 (안전 정지 완료를 뜻하지 않음)
    def _request_cancel(self):
        if self._goal_handle is None or self._cancel_requested:
            return
        job_id = self._active_job_id
        self._cancel_requested = True
        try:
            future = self._goal_handle.cancel_goal_async()
            future.add_done_callback(lambda fut, jid=job_id: self._on_cancel_reply(jid, fut))
        except Exception as exc:
            self._fault(job_id, 'ACTION_CANCEL_ERROR', repr(exc))

    # [핵심 기능] ROS Cancel 응답을 확인하되 PAUSED/STOPPED로 확정하지 않음
    def _on_cancel_reply(self, job_id, future):
        if self._active_job_id != job_id:
            return
        try:
            resp = future.result()
            if not resp.goals_canceling:
                # Goal might finish before cancel is processed. Wait for verified
                # get_result; do NOT mark PAUSED on a Cancel response.
                self.get_logger().warning('Cancel not acknowledged yet; waiting for Action result')
        except Exception as exc:
            self._fault(job_id, 'ACTION_CANCEL_ERROR', repr(exc))

    # [핵심 기능] Controller Action 결과와 펜 이격 여부를 검증해 최종 상태 결정
    def _on_result(self, job_id, future):
        if self._active_job_id != job_id:
            return
        try:
            out = future.result()
            payload = out.result
            valid = self.engine.on_action_result(
                job_id, ros_status=int(out.status), success=bool(payload.success),
                final_state=payload.final_state, completed_strokes=int(payload.completed_strokes),
                pen_up_confirmed=bool(payload.pen_up_confirmed),
                error_code=payload.error_code, message=payload.message)
            if not valid:
                self.get_logger().error('UNCONFIRMED Action result: robot safety not established')
        except Exception as exc:
            self._fault(job_id, 'ACTION_RESULT_ERROR', repr(exc))
        finally:
            self._publish(job_id)
            self._clear_active(job_id)

    # [핵심 기능] 예상하지 못한 오류를 복구 필요 상태로 기록
    def _fault(self, job_id: str, code: str, message: str):
        self.engine.mark_uncertain(job_id, code, message)
        self.get_logger().error(f'{code} job={job_id}: {message}')
        self._publish(job_id)

    # [핵심 기능] 현재 Action 핸들을 해제해 다음 작업 준비
    def _clear_active(self, job_id):
        if self._active_job_id == job_id:
            self._active_job_id = None
            self._goal_handle = None
            self._cancel_requested = False

    def destroy_node(self):
        self.engine.close()
        return super().destroy_node()


# [핵심 기능] 실행 진입점: 환경 변수, ROS 초기화, spin 및 종료 처리
def main(args=None):
    home = Path.home() / 'A4'
    db = Path(os.environ.get('ART_JOB_DB', str(home / 'data' / 'jobs_real_v1.db'))).expanduser().resolve()
    root = Path(os.environ.get('ART_JOB_PLAN_ROOT', str(home / 'data' / 'jobs'))).expanduser().resolve()
    name = os.environ.get('ART_JOB_ACTION_NAME', '/art/execute_drawing')
    timeout = float(os.environ.get('ART_JOB_FEEDBACK_TIMEOUT_SEC', '60'))
    if timeout <= 0:
        raise ValueError('ART_JOB_FEEDBACK_TIMEOUT_SEC must be > 0')
    db.parent.mkdir(parents=True, exist_ok=True)
    with db.with_name(db.name + '.lock').open('a+') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another JobManager uses this database') from exc
        rclpy.init(args=args)
        node = None
        try:
            node = RealJobManagerNode(db_path=db, plan_root=root,
                                      action_name=name, feedback_timeout_sec=timeout)
            rclpy.spin(node)
        except KeyboardInterrupt:
            pass
        finally:
            if node is not None:
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()


if __name__ == '__main__':
    main()
