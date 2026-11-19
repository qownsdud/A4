"""승인된 장비 프로필과 불변 DrawingPlan만 실행하는 M0609 Action 서버."""

import os
from pathlib import Path
import threading
import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.action import ActionServer, GoalResponse, CancelResponse
from art_interfaces.action import ExecuteDrawing
from .doosan_adapter import DoosanAdapter
from .equipment_settings import (
    load_default_equipment_settings,
    load_equipment_settings,
)
from .plan_loader import load_execution_plan
from .live_control_server import LiveControlServer
from .live_motion import LiveMotionSession
from .stroke_executor import (
    DrawingCancelled,
    ExternalForceDetected,
    execute,
    validate_execution,
)


class DrawingNode(Node):
    def __init__(self, *, profile_path=None, adapter_factory=DoosanAdapter):
        super().__init__("drawing_controller")
        self._busy = threading.Lock()
        self._cancel_event = threading.Event()
        self._job_id = None
        self._session = None
        self._settings = None
        a4_root = next((p.parent for p in Path(__file__).resolve().parents if p.name == "ros2_ws"), Path.cwd())
        self.plan_root = Path(
            os.environ.get("ART_JOB_PLAN_ROOT", str(a4_root / "data/jobs"))
        ).expanduser()
        self.adapter = DoosanAdapter()
        path = profile_path or os.environ.get("ART_EQUIPMENT_PROFILE")
        try:
            self._settings = (
                load_equipment_settings(path)
                if path
                else load_default_equipment_settings()
            )
            self.adapter = adapter_factory(self, self._settings)
        except (ValueError, OSError, ImportError, KeyError) as exc:
            self._settings = None
            self.get_logger().error("장비 설정 로드 실패: " + str(exc))
        self.live_control = LiveControlServer(self, on_recover=self._recover_to_home)
        self.server = ActionServer(
            self,
            ExecuteDrawing,
            "/art/execute_drawing",
            execute_callback=self.execute,
            goal_callback=self.goal,
            cancel_callback=self.cancel,
            callback_group=ReentrantCallbackGroup(),
        )

    def _recover_to_home(self):
        if not self._busy.acquire(timeout=5.0):
            return False, "UNKNOWN", "CONTROLLER_BUSY"
        try:
            if self.adapter is not None and hasattr(self.adapter, "return_pen_and_home"):
                self.adapter.return_pen_and_home()
            return True, "STOPPED", ""
        except Exception as exc:
            self.get_logger().warning(f"외력 정지 후 원상복구 중 오류: {exc}")
            return False, "UNKNOWN", str(exc)[:120]
        finally:
            self._busy.release()

    def _plan(self, request):
        return load_execution_plan(
            request.job_id, request.plan_path, request.plan_sha256, root=self.plan_root
        )

    def goal(self, request):
        if not self._busy.acquire(blocking=False):
            return GoalResponse.REJECT
        try:
            plan = self._plan(request)
            if not 1 <= request.start_stroke_id <= len(plan["strokes"]):
                raise ValueError("시작 획 오류")
            validate_execution(plan, self.adapter)
            self._job_id = request.job_id
            self._cancel_event.clear()
            return GoalResponse.ACCEPT
        except Exception as exc:
            self.get_logger().error("실물 실행 거절: " + str(exc))
            self._busy.release()
            return GoalResponse.REJECT

    def cancel(self, handle):
        if self._job_id != handle.request.job_id:
            return CancelResponse.REJECT
        self._cancel_event.set()
        if self._session is not None:
            self._session.request_stop()
        return CancelResponse.ACCEPT

    def execute(self, handle):
        result = ExecuteDrawing.Result()
        result.success = False
        result.final_state = "FAILED"
        result.completed_strokes = handle.request.start_stroke_id - 1
        session = None

        def feedback(event, stroke_id=0, pen_id=""):
            if event == "STROKE_COMPLETED":
                result.completed_strokes = stroke_id
            message = ExecuteDrawing.Feedback(
                event=event,
                stroke_id=stroke_id,
                pen_id=pen_id,
                message="실물 관측 기반 실행 상태",
            )
            handle.publish_feedback(message)

        def cancelled():
            return (
                self._cancel_event.is_set()
                or handle.is_cancel_requested
                or not rclpy.ok()
            )

        try:
            if cancelled():
                raise DrawingCancelled()
            plan = self._plan(handle.request)
            validate_execution(plan, self.adapter)
            self.adapter.preflight()
            if cancelled():
                raise DrawingCancelled()
            session = LiveMotionSession(
                handle.request.job_id,
                bytes(handle.goal_id.uuid).hex(),
                self.adapter,
                feedback,
            )
            self._session = session
            self.live_control.bind(session)
            feedback("STARTED_LIVE")
            execute(
                plan,
                self.adapter,
                handle.request.start_stroke_id,
                session=session,
                cancelled=cancelled,
                feedback=feedback,
            )
            while not session.finish():
                if cancelled():
                    raise DrawingCancelled()
                if session.state == "FAILED":
                    raise RuntimeError("실행 문맥 실패")
                session.wait_running(0.02)
            result.success = True
            result.final_state = "COMPLETED"
            handle.succeed()
        except ExternalForceDetected as exc:
            self.get_logger().warning(f"외력 감지 즉시 정지: {exc}")
            feedback("EXTERNAL_FORCE_STOP", result.completed_strokes, "")
            if session is not None:
                try:
                    session.cancel()
                except Exception:
                    pass
            result.final_state = "INTERRUPTED_SAFE"
            result.error_code = "EXTERNAL_FORCE_DETECTED"
            result.message = str(exc)[:300]
            handle.abort()
        except DrawingCancelled:
            try:
                safe = session.cancel() if session else True
            except Exception:
                safe = False
            if hasattr(self.adapter, "return_pen_and_home"):
                try:
                    self.adapter.return_pen_and_home()
                except Exception as rec_exc:
                    self.get_logger().warning(f"중단 후 원상복구 중 오류: {rec_exc}")
            if safe:
                result.final_state = "INTERRUPTED_SAFE"
                handle.canceled()
            else:
                result.error_code = "STOP_UNCONFIRMED"
                handle.abort()
        except Exception as exc:
            self.get_logger().error(f"실물 실행 실패 ({type(exc).__name__}): {exc}")
            if session is not None:
                session.cancel()
            if (
                (self.adapter.held_pen is not None or getattr(self.adapter, "held_stick_pose", None) is not None)
                and hasattr(self.adapter, "return_pen_and_home")
            ):
                try:
                    self.adapter.return_pen_and_home()
                except Exception as rec_exc:
                    self.get_logger().warning(f"예외 후 펜 반납 중 오류: {rec_exc}")
            result.error_code = type(exc).__name__
            result.message = str(exc)[:300]
            handle.abort()
        finally:
            if session is not None:
                self.live_control.unbind(session)
            self._session = None
            self._job_id = None
            self._busy.release()
        return result

    def destroy_node(self):
        self._cancel_event.set()
        if self._session is not None:
            self._session.request_stop()
        if self.server is not None:
            self.server.destroy()
            self.server = None
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = DrawingNode()
    executor = MultiThreadedExecutor(num_threads=6)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node._cancel_event.set()
        if node._session is not None:
            node._session.request_stop()
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
