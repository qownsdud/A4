"""Kiosk DrawingPlan을 draw_image_standalone.py로 실행하는 경량 ROS2 브리지 노드."""

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
from rclpy.node import Node

from art_interfaces.msg import JobStatus
from art_interfaces.srv import ControlJob, CreateJob

from .pipeline_runner import job_root
from .plan import PlanError, load_plan

DEFAULT_STANDALONE_SCRIPT = str(
    Path.home()
    / "ws_cobot_pjt/ws_dsr/src/collaborate1/collaborate1/app/draw_image_standalone.py"
)
DEFAULT_WS_DSR_SETUP = str(Path.home() / "ws_cobot_pjt/ws_dsr/install/setup.bash")
PROGRESS_RE = re.compile(r"\[(펜\s*\d+)\]\s*진행\s*(\d+)/(\d+)\s*획")


def _env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def plan_to_standalone_strokes(plan_path: Path, out_path: Path) -> int:
    """drawing_plan.json의 points_mm를 draw_image_standalone.py용 strokes_px JSON으로 변환합니다."""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    strokes = [stroke["points_mm"] for stroke in plan.get("strokes", []) if len(stroke.get("points_mm", [])) >= 2]
    if not strokes:
        raise ValueError("drawing_plan.json에 유효한 획이 없습니다.")
    out_path.write_text(
        json.dumps({"strokes_px": strokes, "source_plan": str(plan_path)}, ensure_ascii=False),
        encoding="utf-8",
    )
    return len(strokes)


class StandaloneDrawerNode(Node):
    """/art/create_job 요청을 받아 draw_image_standalone.py를 실행하고 /art/job_status를 발행합니다."""

    def __init__(self) -> None:
        super().__init__("standalone_drawer_node")
        self.declare_parameter("script_path", os.environ.get("ART_STANDALONE_SCRIPT", DEFAULT_STANDALONE_SCRIPT))
        self.declare_parameter("ws_dsr_setup", os.environ.get("ART_WS_DSR_SETUP", DEFAULT_WS_DSR_SETUP))
        self.declare_parameter("virtual", _env_flag("ART_STANDALONE_VIRTUAL", False))
        self.declare_parameter("dry_run", _env_flag("ART_STANDALONE_DRY_RUN", False))
        self.declare_parameter("skip_cal", _env_flag("ART_STANDALONE_SKIP_CAL", False))

        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen[str]] = None
        self._status: Optional[dict] = None
        self._pen_offset: int = 0
        self._last_pen: str = ""
        self._last_pen_done: int = 0

        self._pub = self.create_publisher(JobStatus, "/art/job_status", 10)
        self._create_srv = self.create_service(CreateJob, "/art/create_job", self._on_create_job)
        self._control_srv = self.create_service(ControlJob, "/art/control_job", self._on_control_job)
        self._timer = self.create_timer(0.5, self._publish_status)
        self.get_logger().info("StandaloneDrawerNode 준비 완료 (/art/create_job -> draw_image_standalone.py)")

    def _publish_status(self) -> None:
        if not rclpy.ok():
            return
        with self._lock:
            if not self._status:
                return
            st = dict(self._status)
        msg = JobStatus()
        msg.job_id = st["job_id"]
        msg.state = st["state"]
        msg.completed_strokes = int(st["completed_strokes"])
        msg.total_strokes = max(1, int(st["total_strokes"]))
        msg.current_pen = st["current_pen"]
        msg.error_code = st["error_code"]
        msg.message = st["message"]
        try:
            self._pub.publish(msg)
        except Exception:
            pass

    def _on_create_job(self, request: CreateJob.Request, response: CreateJob.Response) -> CreateJob.Response:
        job_id = (request.job_id or "").strip()
        plan_path_str = (request.plan_path or "").strip()
        response.job_id = job_id

        with self._lock:
            active = self._status and self._status["state"] in ("DISPATCHING", "DRAWING", "STOPPING")
            if active:
                response.accepted = False
                response.state = self._status["state"]
                response.error_code = "JOB_ALREADY_ACTIVE"
                response.message = f"다른 작업({self._status['job_id']})이 이미 실행 중입니다."
                return response

        try:
            summary = load_plan(job_id, plan_path_str, plan_root=job_root())
            plan_path = Path(summary.path)
            strokes_path = plan_path.parent / "standalone_strokes.json"
            total_strokes = plan_to_standalone_strokes(plan_path, strokes_path)
        except (PlanError, OSError, ValueError, json.JSONDecodeError) as exc:
            response.accepted = False
            response.state = "STOPPED"
            response.error_code = "INVALID_PLAN"
            response.message = f"그리기 계획 검증 실패: {exc}"
            return response

        script_path = Path(self.get_parameter("script_path").value)
        if not script_path.is_file():
            response.accepted = False
            response.state = "STOPPED"
            response.error_code = "SCRIPT_NOT_FOUND"
            response.message = f"draw_image_standalone.py를 찾을 수 없습니다: {script_path}"
            return response

        with self._lock:
            self._pen_offset = 0
            self._last_pen = ""
            self._last_pen_done = 0
            self._status = {
                "job_id": job_id,
                "state": "DISPATCHING",
                "completed_strokes": 0,
                "total_strokes": max(1, total_strokes),
                "current_pen": "PEN_1",
                "error_code": "",
                "message": "로봇 드로잉을 시작합니다.",
            }

        self._publish_status()
        worker = threading.Thread(
            target=self._run_standalone,
            args=(job_id, strokes_path, total_strokes),
            daemon=True,
        )
        worker.start()

        response.accepted = True
        response.state = "DISPATCHING"
        response.error_code = ""
        response.message = "Standalone 드로잉 작업이 등록되었습니다."
        return response

    def _on_control_job(self, request: ControlJob.Request, response: ControlJob.Response) -> ControlJob.Response:
        job_id = (request.job_id or "").strip()
        cmd = (request.command or "").strip().upper()
        response.job_id = job_id

        with self._lock:
            st = self._status
            proc = self._proc
            if not st or st["job_id"] != job_id:
                response.accepted = False
                response.state = "STOPPED"
                response.error_code = "JOB_NOT_FOUND"
                response.message = "현재 실행 중인 해당 작업이 없습니다."
                return response
            if cmd != "CANCEL":
                response.accepted = False
                response.state = st["state"]
                response.error_code = "UNSUPPORTED_COMMAND"
                response.message = "Standalone 모드에서는 CANCEL(중단)만 지원합니다."
                return response
            if st["state"] in ("COMPLETED", "STOPPED"):
                response.accepted = True
                response.state = st["state"]
                response.error_code = ""
                response.message = "이미 종료된 작업입니다."
                return response
            st["state"] = "STOPPING"
            st["message"] = "안전 복귀 및 중단 요청 중입니다."

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

        self._publish_status()
        response.accepted = True
        response.state = "STOPPING"
        response.error_code = ""
        response.message = "로봇 안전 복귀를 요청했습니다."
        return response

    def _build_command(self, strokes_path: Path) -> list[str]:
        script_path = str(self.get_parameter("script_path").value)
        ws_dsr_setup = str(self.get_parameter("ws_dsr_setup").value)
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

        if ws_dsr_setup and Path(ws_dsr_setup).is_file():
            quoted = " ".join(shlex.quote(arg) for arg in py_cmd)
            return ["bash", "-c", f"source {shlex.quote(ws_dsr_setup)} && exec {quoted}"]
        return py_cmd

    def _run_standalone(self, job_id: str, strokes_path: Path, total_strokes: int) -> None:
        cmd = self._build_command(strokes_path)
        self.get_logger().info(f"[{job_id}] 실행: {' '.join(cmd)}")
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            with self._lock:
                if self._status and self._status["job_id"] == job_id:
                    self._status.update(
                        state="STOPPED",
                        error_code="LAUNCH_FAILED",
                        message=f"실행 실패: {exc}",
                    )
            self._publish_status()
            return

        with self._lock:
            self._proc = proc
            if self._status and self._status["job_id"] == job_id and self._status["state"] == "DISPATCHING":
                self._status["state"] = "DRAWING"
                self._status["message"] = "로봇이 그리기를 진행 중입니다."
        self._publish_status()

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
                match = PROGRESS_RE.search(line)
                if match:
                    pen_label, done_str, _ = match.groups()
                    done = int(done_str)
                    with self._lock:
                        if self._last_pen and pen_label != self._last_pen:
                            self._pen_offset += self._last_pen_done
                        self._last_pen = pen_label
                        self._last_pen_done = done
                        if self._status and self._status["job_id"] == job_id:
                            self._status["current_pen"] = pen_label.replace("펜 ", "PEN_")
                            self._status["completed_strokes"] = min(total_strokes, self._pen_offset + done)

        rc = proc.wait()
        with self._lock:
            self._proc = None
            st = self._status
            if st and st["job_id"] == job_id:
                if st["state"] == "STOPPING":
                    st.update(state="STOPPED", error_code="", message="사용자 요청으로 중단 및 홈 복귀를 완료했습니다.")
                elif rc == 0:
                    st.update(
                        state="COMPLETED",
                        completed_strokes=total_strokes,
                        error_code="",
                        message="로봇 그리기가 완료되었습니다.",
                    )
                else:
                    tail = last_lines[-1] if last_lines else f"exit code {rc}"
                    st.update(
                        state="STOPPED",
                        error_code="DRAW_FAILED",
                        message=f"로봇 그리기 오류 (code={rc}): {tail[:200]}",
                    )
        self._publish_status()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = StandaloneDrawerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
