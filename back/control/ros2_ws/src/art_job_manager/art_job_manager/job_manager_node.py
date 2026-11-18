# [파일 역할] 실제 JobManager ROS 2 노드 (기본 실행)
# [동작] CreateJob/ControlJob Service와 JobStatus Topic을 제공하고 ExecuteDrawing Action Client를 실행합니다.
# [주의] DrawingController Action Server가 없으면 QUEUED로 대기하며 가짜 진행률을 만들지 않습니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""A4 production JobManager ROS 2 services + real DrawingController Action client.

Run with: ros2 run art_job_manager job_manager
Default: NO simulation. Without a compatible /art/execute_drawing Action server,
accepted jobs remain QUEUED and no progress is fabricated.

TEAM_SYNC(Robot): Implement ExecuteDrawing Action server; only trusted observed
feedback proves stroke completion. Cancel must stop motion and lift the pen.
TEAM_SYNC(Backend/UI): CreateJob accepts already validated DrawingPlan path.
TEAM_SYNC(Operations): E-Stop is physical, not this ROS service.
"""

from __future__ import annotations

import fcntl
import threading
from functools import wraps
import os
import time
import uuid
from pathlib import Path

import rclpy
from rclpy.action import ActionClient
from rclpy.action.graph import get_action_server_names_and_types_by_node
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from unique_identifier_msgs.msg import UUID
from art_interfaces.action import ExecuteDrawing
from art_interfaces.msg import JobStatus
from art_interfaces.srv import CreateJob, ControlJob, ControlDrawing

from .production_engine import ProductionEngine, Reply


def serialized(callback):
    """Future 완료 콜백도 HTTP/Timer 콜백과 같은 실행 문맥에서 처리합니다."""
    @wraps(callback)
    def locked(self, *args, **kwargs):
        with self._callback_lock:
            return callback(self, *args, **kwargs)
    return locked


# [핵심 기능] 실제 Controller Action과 통신하는 JobManager의 ROS 인터페이스
class RealJobManagerNode(Node):
    def __init__(self, *, db_path: Path, plan_root: Path,
                 action_name: str = '/art/execute_drawing',
                 feedback_timeout_sec: float = 60.0):
        super().__init__('job_manager_node')
        self._callback_lock = threading.RLock()
        self._closing = False
        self.engine = ProductionEngine(db_path, plan_root=plan_root)
        self.action_name = action_name
        self.feedback_timeout_sec = feedback_timeout_sec
        self.action_client = ActionClient(self, ExecuteDrawing, action_name)
        # rclpy는 Result 수신 시 내부 피드백 콜백을 해제하므로 별도 구독으로
        # 이미 전송된 마지막 피드백까지 처리합니다. Goal UUID로 다른 실행을 배제합니다.
        self.feedback_sub = self.create_subscription(
            ExecuteDrawing.Impl.FeedbackMessage, action_name.rstrip('/') + '/_action/feedback',
            self._on_wire_feedback,
            QoSProfile(depth=1000, reliability=ReliabilityPolicy.RELIABLE))
        self._active_goal_uuid = None
        self.motion_client = self.create_client(ControlDrawing, '/art/control_drawing')
        self._live_mode = None
        self._desired_control = None
        self._live_call = None
        self.status_pub = self.create_publisher(JobStatus, '/art/job_status', 10)
        self.create_srv = self.create_service(CreateJob, '/art/create_job', self._create)
        self.control_srv = self.create_service(ControlJob, '/art/control_job', self._control)
        self.timer = self.create_timer(0.3, self._poll)
        self._active_job_id: str | None = None
        self._goal_handle = None
        self._cancel_requested = False
        self._last_feedback = time.monotonic()
        self._next_warn = 0.0
        self._pending_result = None
        if self.engine.recovered_jobs:
            self.get_logger().error('RECOVERY_REQUIRED on startup: ' + ', '.join(self.engine.recovered_jobs))
        self.get_logger().info('REAL mode only. Awaiting DrawingController Action server: ' + action_name)
        self._publish_all()

    # [핵심 기능] 작업의 상태를 JobStatus ROS Topic으로 발행
    def _publish(self, job_id: str) -> None:
        if self._closing:
            return
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
    @serialized
    def _create(self, request, response):
        result = self.engine.create_job(request.job_id, request.plan_path)
        self._publish(request.job_id)
        return self._reply(response, result)

    # [핵심 기능] ControlJob Service 콜백: 명령 저장 및 안전한 Action 취소 요청
    @serialized
    def _control(self, request, response):
        row = self.engine.status(request.job_id)
        if (request.command == 'RESUME' and row and row['state'] == 'PAUSED' and row['live_execution']
                and (self._active_job_id != request.job_id or self._goal_handle is None
                     or self._live_mode is not True or self._cancel_requested)):
            self._fault(request.job_id,'LIVE_EXECUTION_LOST','동일 실행 문맥을 확인할 수 없습니다.')
            return self._reply(response, Reply(False,request.job_id,'RECOVERY_REQUIRED','LIVE_EXECUTION_LOST'))
        if (request.command == 'PAUSE' and self._active_job_id == request.job_id
                and self._live_mode is False):
            return self._reply(response, Reply(False, request.job_id,
                self.engine.status(request.job_id)['state'], 'CONTINUOUS_PAUSE_UNSUPPORTED',
                '동일 모션 일시정지를 지원하지 않는 Controller입니다.'))
        result = self.engine.control_job(request.job_id, request.command, request.request_id)
        self._publish(request.job_id)
        if result.accepted and self._active_job_id == request.job_id:
            if request.command in ('PAUSE', 'RESUME') and result.state in ('PAUSING', 'RESUMING'):
                if self._desired_control is None or self._desired_control[:2] != (request.command,request.request_id):
                    self._desired_control = (request.command, request.request_id, time.monotonic())
                self._drive_live_control()
            elif request.command == 'CANCEL' and result.state == 'STOPPING':
                self._request_cancel()
        return self._reply(response, result)

    def _controller_server_count(self):
        action_name = self.resolve_topic_name(self.action_name)
        return sum(any(name == action_name for name, _ in
                       get_action_server_names_and_types_by_node(self, node, namespace))
                   for node, namespace in self.get_node_names_and_namespaces())

    # [핵심 기능] 주기적으로 대기 작업을 배차하고 Controller 피드백 시간 초과 감시
    @serialized
    def _poll(self):
        if self._closing:
            return
        now = time.monotonic()
        self._finish_pending_result()
        # Controller action is required for actual progress. Never simulate.
        if self._active_job_id is None:
            queued = [j for j in self.engine.statuses() if j['state'] == 'QUEUED']
            server_count = self._controller_server_count() if queued else 0
            if queued and server_count > 1:
                if now >= self._next_warn:
                    self.get_logger().error('DrawingController 서버 중복: Goal을 보내지 않습니다. Discovery 설정을 확인하세요.')
                    self._next_warn = now + 10.0
                return
            if queued and server_count == 1 and self.action_client.wait_for_server(timeout_sec=0.0):
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
            if job and job['state'] == 'STOPPING':
                self._request_cancel()
            self._drive_live_control()
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
            goal_uuid = UUID(uuid=list(uuid.uuid4().bytes))
            self._active_goal_uuid = bytes(goal_uuid.uuid)
            future = self.action_client.send_goal_async(goal, goal_uuid=goal_uuid)
            future.add_done_callback(lambda fut, job_id=dispatch.job_id: self._on_goal_response(job_id, fut))
        except Exception as exc:
            self._fault(dispatch.job_id, 'ACTION_SEND_ERROR', repr(exc))
            self._clear_active(dispatch.job_id)

    # [핵심 기능] Controller의 Action Goal 수락·거부 확인
    @serialized
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
            if state in ('STOPPING', 'RECOVERY_REQUIRED'):
                self._request_cancel()
        except Exception as exc:
            self._fault(job_id, 'ACTION_RESPONSE_ERROR', repr(exc))
            self._clear_active(job_id)

    @serialized
    def _on_wire_feedback(self, message):
        if (self._active_job_id is not None
                and bytes(message.goal_id.uuid) == self._active_goal_uuid):
            self._on_feedback(self._active_job_id, message)

    # [핵심 기능] Controller가 보고한 시작·진행·완료 이벤트를 상태 머신에 반영
    @serialized
    def _on_feedback(self, job_id, message):
        if self._active_job_id != job_id:
            return
        fb = message.feedback
        event = fb.event
        self._last_feedback = time.monotonic()
        if event == 'HEARTBEAT':
            valid = True  # liveness only, never progress/pen safety
        elif event in ('STARTED', 'STARTED_LIVE'):
            self._live_mode = event == 'STARTED_LIVE'
            valid = self.engine.on_controller_started(job_id, live_execution=self._live_mode)
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
        self._finish_pending_result()

    def _drive_live_control(self):
        if self._active_job_id is None or self._desired_control is None:
            return
        row = self.engine.status(self._active_job_id)
        if row['state'] not in ('PAUSING', 'RESUMING'):
            return
        if self._live_mode is None:
            if time.monotonic()-self._desired_control[2]>5.:
                self._fault(row['job_id'],'CONTROLLER_CAPABILITY_UNKNOWN','동일 모션 유지 여부를 확인하지 못했습니다.')
                self._request_cancel()
            return  # STARTED_LIVE가 오기 전에는 일시정지 대신 Action을 취소하지 않습니다.
        if not self._live_mode:
            self._fault(row['job_id'], 'CONTINUOUS_PAUSE_UNSUPPORTED', '동일 실행 유지 기능이 없습니다.')
            self._request_cancel()
            return
        if self._live_call is not None:
            if time.monotonic() - self._live_call[3] > 5.0:
                self._fault(row['job_id'], 'MOTION_CONTROL_TIMEOUT', '정지·재개 결과가 미확정입니다.')
                self._request_cancel()
            return
        command, request_id, _ = self._desired_control
        execution_id = self._active_goal_uuid.hex()
        token = (row['job_id'], command, request_id, time.monotonic(), execution_id)
        self._live_call = token
        if not self.motion_client.service_is_ready():
            self._fault(row['job_id'], 'MOTION_CONTROL_UNAVAILABLE', 'Controller 제어 서비스가 없습니다.')
            self._request_cancel()
            return
        request = ControlDrawing.Request(job_id=row['job_id'], execution_id=execution_id,
                                         command=command, request_id=request_id)
        try:
            future = self.motion_client.call_async(request)
            future.add_done_callback(lambda f: self._on_live_reply(token, f))
        except Exception as exc:
            self._fault(row['job_id'], 'MOTION_CONTROL_ERROR', repr(exc))
            self._request_cancel()

    @serialized
    def _on_live_reply(self, token, future):
        job_id, command, request_id, _, execution_id = token
        if (self._live_call != token or self._active_job_id != job_id
                or self._active_goal_uuid.hex() != execution_id):
            return
        self._live_call = None
        row = self.engine.status(job_id)
        if row['state'] in ('STOPPING', 'RECOVERY_REQUIRED'):
            return  # 지연된 재개 응답으로 취소/미확정 상태를 되돌리지 않습니다.
        try:
            reply = future.result()
            expected = 'PAUSED' if command == 'PAUSE' else 'DRAWING'
            if reply is None or not reply.accepted or reply.state != expected:
                raise RuntimeError(getattr(reply, 'error_code', 'NO_REPLY'))
            if not self.engine.on_live_control(job_id, command):
                raise RuntimeError('상태 전이 불일치')
            self._desired_control = None
            self._last_feedback = time.monotonic()
            self._publish(job_id)
        except Exception as exc:
            self._fault(job_id, 'MOTION_CONTROL_UNCONFIRMED', repr(exc))
            self._request_cancel()

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
    @serialized
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
    @serialized
    def _on_result(self, job_id, future):
        if self._active_job_id != job_id:
            return
        try:
            out = future.result()
            # Result 서비스와 Feedback 토픽은 서로 다른 통신 경로입니다.
            # 결과가 앞서 도착해도 완료 이벤트를 만들어내지 않고 실제 피드백만 기다립니다.
            self._pending_result = (job_id, out, time.monotonic() + 2.0)
            self._finish_pending_result()
        except Exception as exc:
            self._fault(job_id, 'ACTION_RESULT_ERROR', repr(exc))
            self._clear_active(job_id)

    def _finish_pending_result(self):
        pending = self._pending_result
        if pending is None:
            return
        job_id, out, deadline = pending
        row = self.engine.status(job_id)
        payload = out.result
        if (row and row['state'] != 'RECOVERY_REQUIRED'
                and payload.final_state in ('COMPLETED', 'INTERRUPTED_SAFE')
                and row['completed_strokes'] < int(payload.completed_strokes) <= row['total_strokes']
                and time.monotonic() < deadline):
            return
        self._pending_result = None
        try:
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
        if self._closing:
            return
        self.engine.mark_uncertain(job_id, code, message)
        self.get_logger().error(f'{code} job={job_id}: {message}')
        self._publish(job_id)

    # [핵심 기능] 현재 Action 핸들을 해제해 다음 작업 준비
    def _clear_active(self, job_id):
        if self._active_job_id == job_id:
            self._active_job_id = None
            self._pending_result = None
            self._active_goal_uuid = None
            self._live_mode = None
            self._desired_control = None
            self._live_call = None
            self._goal_handle = None
            self._cancel_requested = False

    @serialized
    def destroy_node(self):
        if self._closing:
            return
        if self._active_job_id is not None:
            self.engine.mark_uncertain(self._active_job_id, 'MANAGER_SHUTDOWN',
                                       'Manager 종료: 실제 모션 상태 확인 필요')
            if rclpy.ok():
                self._request_cancel()  # 최선의 취소 요청이며 물리 정지 완료를 의미하지 않습니다.
        self._closing = True
        self.timer.cancel()
        self._active_job_id = None
        self._pending_result = None
        self.action_client.destroy()
        result = super().destroy_node()
        self.engine.close()
        return result


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
