"""JobManager의 ExecuteDrawing 계약을 구현해 draw_image_standalone.py를 실행하는 Action 서버."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import threading
import time
from typing import Optional

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from art_interfaces.action import ExecuteDrawing
from art_interfaces.srv import ControlDrawing


def _default_standalone_script() -> str:
    try:
        from art_artwork_pipeline import draw_image_standalone as _mod
        return str(Path(_mod.__file__).resolve())
    except ImportError:
        return str(
            Path(__file__).resolve().parents[2]
            / "art_artwork_pipeline/art_artwork_pipeline/draw_image_standalone.py"
        )


PROGRESS_RE = re.compile(r"\[(펜\s*\d+)\]\s*진행\s*(\d+)/(\d+)\s*획")


def _env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def plan_to_standalone_strokes(plan_path: Path, out_path: Path) -> int:
    """drawing_plan.json의 points_mm를 draw_image_standalone.py용 strokes_px JSON으로 변환합니다."""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    valid = [
        stroke
        for stroke in plan.get("strokes", [])
        if len(stroke.get("points_mm", [])) >= 2
    ]
    strokes = [stroke["points_mm"] for stroke in valid]
    pen_ids = [stroke.get("pen_id", "PEN_1") for stroke in valid]
    z_deltas = [
        [float(v) for v in stroke["z_deltas_mm"]]
        if isinstance(stroke.get("z_deltas_mm"), list) and len(stroke["z_deltas_mm"]) == len(stroke["points_mm"])
        else [0.0] * len(stroke["points_mm"])
        for stroke in valid
    ]
    if not strokes:
        raise ValueError("drawing_plan.json에 유효한 획이 없습니다.")
    out_path.write_text(
        json.dumps(
            {"strokes_px": strokes, "pen_ids": pen_ids, "z_deltas_mm": z_deltas, "source_plan": str(plan_path)},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return len(strokes)


class StandaloneDrawingControllerNode(Node):
    """/art/execute_drawing Action을 받아 draw_image_standalone.py로 실행합니다."""

    def __init__(self) -> None:
        super().__init__("drawing_controller_node")
        self.declare_parameter("script_path", os.environ.get("ART_STANDALONE_SCRIPT", _default_standalone_script()))
        self.declare_parameter("virtual", _env_flag("ART_STANDALONE_VIRTUAL", False))
        self.declare_parameter("dry_run", _env_flag("ART_STANDALONE_DRY_RUN", False))
        self.declare_parameter("skip_cal", _env_flag("ART_STANDALONE_SKIP_CAL", False))

        self._cb_group = ReentrantCallbackGroup()
        self._lock = threading.Lock()
        self._active_job_id: Optional[str] = None
        self._proc: Optional[subprocess.Popen[str]] = None

        self._action_server = ActionServer(
            self,
            ExecuteDrawing,
            "/art/execute_drawing",
            execute_callback=self._execute_cb,
            goal_callback=self._goal_cb,
            cancel_callback=self._cancel_cb,
            callback_group=self._cb_group,
        )
        self._control_srv = self.create_service(
            ControlDrawing,
            "/art/control_drawing",
            self._on_control_drawing,
            callback_group=self._cb_group,
        )
        self.get_logger().info("StandaloneDrawingControllerNode 준비 완료 (/art/execute_drawing -> draw_image_standalone.py)")

    def _goal_cb(self, goal_request: ExecuteDrawing.Goal) -> GoalResponse:
        with self._lock:
            if self._active_job_id is not None:
                self.get_logger().warning(f"이미 실행 중인 작업({self._active_job_id})이 있어 Goal 거절")
                return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _cancel_cb(self, goal_handle) -> CancelResponse:
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write("x\n")
                    proc.stdin.flush()
                else:
                    proc.send_signal(signal.SIGINT)
            except OSError:
                try:
                    proc.send_signal(signal.SIGINT)
                except OSError:
                    pass
        return CancelResponse.ACCEPT

    def _on_control_drawing(self, request: ControlDrawing.Request, response: ControlDrawing.Response) -> ControlDrawing.Response:
        response.accepted = False
        response.state = "UNKNOWN"
        response.error_code = "NOT_SUPPORTED_IN_STANDALONE"
        response.message = "Standalone 실행기는 PAUSE/RESUME을 지원하지 않습니다. 중단(CANCEL)만 가능합니다."
        return response

    def _build_command(self, strokes_path: Path) -> list[str]:
        script_path = str(self.get_parameter("script_path").value)
        virtual = bool(self.get_parameter("virtual").value)
        dry_run = bool(self.get_parameter("dry_run").value)
        skip_cal = bool(self.get_parameter("skip_cal").value)

        py_cmd = ["python3", "-u", script_path, "--input", str(strokes_path)]
        if virtual:
            py_cmd.append("--virtual")
        if dry_run:
            py_cmd.append("--dry-run")
        if skip_cal:
            py_cmd.append("--skip-cal")
        return py_cmd

    def _publish_feedback(self, goal_handle, *, event: str, stroke_id: int = 0, pen_id: str = "", message: str = "") -> None:
        fb = ExecuteDrawing.Feedback()
        fb.stroke_id = int(stroke_id)
        fb.event = event
        fb.pen_id = pen_id
        fb.message = message
        goal_handle.publish_feedback(fb)

    def _execute_cb(self, goal_handle) -> ExecuteDrawing.Result:
        goal = goal_handle.request
        job_id = goal.job_id
        plan_path = Path(goal.plan_path)
        result = ExecuteDrawing.Result()

        with self._lock:
            self._active_job_id = job_id

        try:
            script_path = Path(self.get_parameter("script_path").value)
            if not script_path.is_file():
                goal_handle.abort()
                result.success = False
                result.final_state = "FAILED"
                result.completed_strokes = 0
                result.error_code = "SCRIPT_NOT_FOUND"
                result.message = f"draw_image_standalone.py를 찾을 수 없습니다: {script_path}"
                return result

            strokes_path = plan_path.parent / "standalone_strokes.json"
            total_strokes = plan_to_standalone_strokes(plan_path, strokes_path)
            self._publish_feedback(
                goal_handle,
                event="STARTED",
                stroke_id=0,
                pen_id="PEN_1",
                message="draw_image_standalone.py 실행을 시작합니다.",
            )

            cmd = self._build_command(strokes_path)
            self.get_logger().info(f"[{job_id}] 실행: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with self._lock:
                self._proc = proc

            pen_offset = 0
            last_pen = ""
            last_pen_done = 0
            reported_strokes = 0
            last_lines: list[str] = []

            if proc.stdout:
                for raw_line in proc.stdout:
                    line = raw_line.rstrip()
                    if not line:
                        continue
                    last_lines.append(line)
                    if len(last_lines) > 10:
                        last_lines.pop(0)
                    self.get_logger().info(f"[{job_id}] {line}")

                    if goal_handle.is_cancel_requested and proc.poll() is None and proc.stdin:
                        try:
                            proc.stdin.write("x\n")
                            proc.stdin.flush()
                        except OSError:
                            pass

                    match = PROGRESS_RE.search(line)
                    if match:
                        pen_label, done_str, _ = match.groups()
                        done = int(done_str)
                        if last_pen and pen_label != last_pen:
                            pen_offset += last_pen_done
                        last_pen = pen_label
                        last_pen_done = done
                        pen_id = pen_label.replace("펜 ", "PEN_")
                        target_done = min(total_strokes, pen_offset + done)
                        while reported_strokes < target_done:
                            reported_strokes += 1
                            self._publish_feedback(
                                goal_handle,
                                event="STROKE_COMPLETED",
                                stroke_id=reported_strokes,
                                pen_id=pen_id,
                                message=f"{pen_label} 진행 {reported_strokes}/{total_strokes}획",
                            )

            rc = proc.wait()
            with self._lock:
                self._proc = None

            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                result.success = False
                result.final_state = "INTERRUPTED_SAFE"
                result.completed_strokes = reported_strokes
                result.error_code = "CANCELED"
                result.message = "사용자 요청으로 안전 복귀 후 중단했습니다."
                return result

            if rc == 0:
                while reported_strokes < total_strokes:
                    reported_strokes += 1
                    self._publish_feedback(
                        goal_handle,
                        event="STROKE_COMPLETED",
                        stroke_id=reported_strokes,
                        pen_id=last_pen.replace("펜 ", "PEN_") if last_pen else "PEN_3",
                        message=f"획 {reported_strokes}/{total_strokes} 완료",
                    )
                goal_handle.succeed()
                result.success = True
                result.final_state = "COMPLETED"
                result.completed_strokes = total_strokes
                result.error_code = ""
                result.message = "draw_image_standalone.py 그리기를 완료했습니다."
                return result

            tail = last_lines[-1] if last_lines else f"exit code {rc}"
            goal_handle.abort()
            result.success = False
            result.final_state = "FAILED"
            result.completed_strokes = reported_strokes
            result.error_code = "STANDALONE_DRAW_FAILED"
            result.message = f"로봇 그리기 오류 (code={rc}): {tail[:200]}"
            return result
        except Exception as exc:
            goal_handle.abort()
            result.success = False
            result.final_state = "FAILED"
            result.completed_strokes = 0
            result.error_code = type(exc).__name__
            result.message = str(exc)
            return result
        finally:
            with self._lock:
                self._proc = None
                self._active_job_id = None


def main(args=None) -> None:
    rclpy.init(args=args)
    node = StandaloneDrawingControllerNode()
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
