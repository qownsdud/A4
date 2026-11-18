"""SQLite와 분리된 순수 인메모리 JobManager ROS2 노드입니다."""

from __future__ import annotations

import threading
import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from art_interfaces.action import ExecuteDrawing
from art_interfaces.msg import JobStatus
from art_interfaces.srv import ControlDrawing, ControlJob, CreateJob

from .decision_port import DecisionSink, LoggingDecisionSink
from .plan_validator import default_plan_root
from .state_machine import CommandReply, JobStateMachine


class JobManagerNode(Node):
    """KioskBridge 요청을 받아 상태 머신으로 결정하고 실행기·상태 토픽을 연결합니다."""

    def __init__(self, *, decision_sink: DecisionSink | None = None) -> None:
        super().__init__("job_manager_node")
        self._cb_group = ReentrantCallbackGroup()
        sink = decision_sink or LoggingDecisionSink(self.get_logger())
        self.machine = JobStateMachine(plan_root=default_plan_root(), decision_sink=sink)

        self._lock = threading.RLock()
        self._goal_handles: dict[str, object] = {}

        self._status_pub = self.create_publisher(JobStatus, "/art/job_status", 10)
        self._create_srv = self.create_service(
            CreateJob, "/art/create_job", self._on_create_job, callback_group=self._cb_group
        )
        self._control_srv = self.create_service(
            ControlJob, "/art/control_job", self._on_control_job, callback_group=self._cb_group
        )
        self._exec_client = ActionClient(
            self, ExecuteDrawing, "/art/execute_drawing", callback_group=self._cb_group
        )
        self._ctrl_client = self.create_client(
            ControlDrawing, "/art/control_drawing", callback_group=self._cb_group
        )
        self.get_logger().info("JobManagerNode 준비 완료 (인메모리 중앙 제어 + 단방향 결정 포트)")

    def _publish_status(self, job_id: str) -> None:
        snap = self.machine.status(job_id)
        if snap is None or not rclpy.ok():
            return
        msg = JobStatus(
            job_id=snap.job_id,
            state=snap.state,
            completed_strokes=int(snap.completed_strokes),
            total_strokes=int(snap.total_strokes),
            current_pen=snap.current_pen,
            error_code=snap.error_code,
            message=snap.message,
        )
        try:
            self._status_pub.publish(msg)
        except Exception:
            pass

    @staticmethod
    def _fill_reply(response, reply: CommandReply):
        response.accepted = reply.accepted
        response.job_id = reply.job_id
        response.state = reply.state
        response.error_code = reply.error_code
        response.message = reply.message
        return response

    def _on_create_job(self, request: CreateJob.Request, response: CreateJob.Response) -> CreateJob.Response:
        reply = self.machine.create_job(request.job_id, request.plan_path)
        self._fill_reply(response, reply)
        if reply.accepted:
            self._publish_status(reply.job_id)
            self._dispatch_job(reply.job_id)
        return response

    def _dispatch_job(self, job_id: str) -> None:
        dispatch = self.machine.prepare_dispatch(job_id)
        self._publish_status(job_id)
        if dispatch is None:
            return
        if not self._exec_client.wait_for_server(timeout_sec=2.0):
            self.machine.mark_failed(job_id, "CONTROLLER_UNAVAILABLE", "실행기 Action 서버를 찾을 수 없습니다.")
            self._publish_status(job_id)
            return

        goal = ExecuteDrawing.Goal(
            job_id=dispatch.job_id,
            plan_path=dispatch.plan_path,
            plan_sha256=dispatch.plan_sha256,
            start_stroke_id=dispatch.start_stroke_id,
        )
        future = self._exec_client.send_goal_async(
            goal, feedback_callback=lambda fb, jid=job_id: self._on_feedback(jid, fb)
        )
        future.add_done_callback(lambda fut, jid=job_id: self._on_goal_response(jid, fut))

    def _on_goal_response(self, job_id: str, future) -> None:
        try:
            goal_handle = future.result()
        except Exception as exc:
            self.machine.mark_failed(job_id, "ACTION_GOAL_ERROR", repr(exc))
            self._publish_status(job_id)
            return

        if not goal_handle or not goal_handle.accepted:
            self.machine.mark_failed(job_id, "ACTION_GOAL_REJECTED", "실행기가 Goal을 거절했습니다.")
            self._publish_status(job_id)
            return

        with self._lock:
            self._goal_handles[job_id] = goal_handle
        res_future = goal_handle.get_result_async()
        res_future.add_done_callback(lambda fut, jid=job_id: self._on_result(jid, fut))

    def _on_feedback(self, job_id: str, wrapped) -> None:
        fb = wrapped.feedback
        if self.machine.on_feedback(
            job_id,
            event=fb.event,
            stroke_id=int(fb.stroke_id),
            pen_id=fb.pen_id,
            pen_up_confirmed=bool(fb.pen_up_confirmed),
            message=fb.message,
        ):
            self._publish_status(job_id)

    def _on_result(self, job_id: str, future) -> None:
        with self._lock:
            self._goal_handles.pop(job_id, None)
        try:
            out = future.result()
            res = out.result
            self.machine.on_action_result(
                job_id,
                ros_status=int(out.status),
                success=bool(res.success),
                final_state=res.final_state,
                completed_strokes=int(res.completed_strokes),
                pen_up_confirmed=bool(res.pen_up_confirmed),
                error_code=res.error_code,
                message=res.message,
            )
        except Exception as exc:
            self.machine.mark_failed(job_id, "ACTION_RESULT_ERROR", repr(exc))
        self._publish_status(job_id)

    def _on_control_job(self, request: ControlJob.Request, response: ControlJob.Response) -> ControlJob.Response:
        cmd = (request.command or "").strip().upper()
        reply = self.machine.control_job(request.job_id, cmd, request.request_id)
        self._fill_reply(response, reply)
        if not reply.accepted:
            return response

        self._publish_status(request.job_id)
        if cmd in ("PAUSE", "RESUME"):
            self._send_control_drawing(request.job_id, cmd, request.request_id)
        elif cmd == "CANCEL" and reply.state == "STOPPING":
            self._send_cancel_goal(request.job_id)
        return response

    def _send_control_drawing(self, job_id: str, cmd: str, request_id: str) -> None:
        if not self._ctrl_client.wait_for_service(timeout_sec=1.0):
            self.machine.on_control_reply(
                job_id, cmd, False, error_code="CONTROL_SERVICE_UNAVAILABLE", message="실행기 제어 서비스 없음"
            )
            self._publish_status(job_id)
            return
        req = ControlDrawing.Request(job_id=job_id, command=cmd, request_id=request_id)
        fut = self._ctrl_client.call_async(req)
        fut.add_done_callback(lambda f, jid=job_id, c=cmd: self._on_control_reply(jid, c, f))

    def _on_control_reply(self, job_id: str, cmd: str, future) -> None:
        try:
            res = future.result()
            self.machine.on_control_reply(
                job_id, cmd, bool(res.accepted), error_code=res.error_code, message=res.message
            )
        except Exception as exc:
            self.machine.on_control_reply(
                job_id, cmd, False, error_code="CONTROL_CALL_ERROR", message=repr(exc)
            )
        self._publish_status(job_id)

    def _send_cancel_goal(self, job_id: str) -> None:
        with self._lock:
            handle = self._goal_handles.get(job_id)
        if handle is None:
            self.machine.mark_failed(job_id, "CANCELED_NO_GOAL", "실행 핸들이 없어 중단 처리했습니다.")
            self._publish_status(job_id)
            return
        try:
            handle.cancel_goal_async()
        except Exception as exc:
            self.machine.mark_failed(job_id, "CANCEL_ERROR", repr(exc))
            self._publish_status(job_id)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = JobManagerNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
