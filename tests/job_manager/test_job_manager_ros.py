"""JobManagerNode 실제 ROS2 Service/Action/Topic 통신 통합 테스트."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

rclpy = pytest.importorskip("rclpy")
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from art_interfaces.action import ExecuteDrawing
from art_interfaces.msg import JobStatus
from art_interfaces.srv import ControlDrawing, ControlJob, CreateJob
from art_job_manager.decision_port import MemoryDecisionSink
from art_job_manager.job_manager_node import JobManagerNode


def _make_plan(root: Path, job_id: str, stroke_count: int = 2) -> str:
    job_dir = root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "drawing_plan.json"
    strokes = [
        {
            "stroke_id": i,
            "execution_order": i - 1,
            "pen_id": f"PEN_{((i - 1) % 3) + 1}",
            "points_mm": [[10.0 * i, 10.0], [10.0 * i + 5.0, 20.0]],
        }
        for i in range(1, stroke_count + 1)
    ]
    payload = {
        "schema_version": "0.2",
        "job_id": job_id,
        "unit": "mm",
        "coordinate_frame": "paper_top_left_x_right_y_down",
        "paper_mm": {"width": 297, "height": 210},
        "strokes": strokes,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


class FakeControllerNode(Node):
    """가짜 /art/execute_drawing 및 /art/control_drawing 서버입니다."""

    def __init__(self) -> None:
        super().__init__("fake_drawing_controller")
        self._cb = ReentrantCallbackGroup()
        self.mode = "normal"  # normal | wait_pause_resume | wait_cancel | fail
        self.paused = threading.Event()
        self.resumed = threading.Event()
        self.release_finish = threading.Event()
        self.received_goals: list[ExecuteDrawing.Goal] = []

        self._action_srv = ActionServer(
            self,
            ExecuteDrawing,
            "/art/execute_drawing",
            execute_callback=self._on_execute,
            goal_callback=lambda _req: GoalResponse.ACCEPT,
            cancel_callback=lambda _handle: CancelResponse.ACCEPT,
            callback_group=self._cb,
        )
        self._ctrl_srv = self.create_service(
            ControlDrawing,
            "/art/control_drawing",
            self._on_control,
            callback_group=self._cb,
        )

    def reset(self, mode: str = "normal") -> None:
        self.mode = mode
        self.paused.clear()
        self.resumed.clear()
        self.release_finish.clear()

    def _on_control(self, req: ControlDrawing.Request, res: ControlDrawing.Response) -> ControlDrawing.Response:
        if req.command == "PAUSE":
            self.paused.set()
            res.accepted = True
            res.state = "PAUSED"
            res.message = "가짜 일시정지 완료"
            return res
        if req.command == "RESUME":
            self.resumed.set()
            res.accepted = True
            res.state = "DRAWING"
            res.message = "가짜 재개 완료"
            return res
        res.accepted = False
        res.error_code = "UNSUPPORTED"
        return res

    def _on_execute(self, handle) -> ExecuteDrawing.Result:
        self.received_goals.append(handle.request)
        res = ExecuteDrawing.Result()

        if self.mode == "fail":
            res.success = False
            res.final_state = "FAILED"
            res.completed_strokes = 0
            res.error_code = "MOCK_FAIL"
            res.message = "가짜 실행기 실패"
            handle.abort()
            return res

        handle.publish_feedback(
            ExecuteDrawing.Feedback(
                stroke_id=0, event="STARTED_LIVE", pen_id="PEN_1", message="시작"
            )
        )
        time.sleep(0.05)

        if self.mode == "wait_pause_resume":
            handle.publish_feedback(
                ExecuteDrawing.Feedback(
                    stroke_id=1, event="STROKE_COMPLETED", pen_id="PEN_1", message="1획"
                )
            )
            assert self.resumed.wait(timeout=5.0), "RESUME 신호를 받지 못했습니다."
            handle.publish_feedback(
                ExecuteDrawing.Feedback(
                    stroke_id=2, event="STROKE_COMPLETED", pen_id="PEN_2", message="2획"
                )
            )
            res.success = True
            res.final_state = "COMPLETED"
            res.completed_strokes = 2
            handle.succeed()
            return res

        if self.mode == "wait_cancel":
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if handle.is_cancel_requested:
                    res.success = False
                    res.final_state = "INTERRUPTED_SAFE"
                    res.completed_strokes = 0
                    res.message = "안전 중단 완료"
                    handle.canceled()
                    return res
                time.sleep(0.02)
            handle.abort()
            return res

        # normal mode: 2 strokes
        for sid, pen in ((1, "PEN_1"), (2, "PEN_2")):
            handle.publish_feedback(
                ExecuteDrawing.Feedback(
                    stroke_id=sid, event="STROKE_COMPLETED", pen_id=pen, message=f"{sid}획 완료"
                )
            )
            time.sleep(0.03)

        self.release_finish.wait(timeout=0.5)
        res.success = True
        res.final_state = "COMPLETED"
        res.completed_strokes = 2
        res.message = "완료"
        handle.succeed()
        return res


class ClientHarness(Node):
    """Bridge 역할을 대신해 CreateJob/ControlJob 호출 및 JobStatus를 수집합니다."""

    def __init__(self) -> None:
        super().__init__("test_bridge_client")
        self._cb = ReentrantCallbackGroup()
        self.create_cli = self.create_client(CreateJob, "/art/create_job", callback_group=self._cb)
        self.control_cli = self.create_client(ControlJob, "/art/control_job", callback_group=self._cb)
        self.statuses: list[JobStatus] = []
        self._lock = threading.Lock()
        self.create_subscription(JobStatus, "/art/job_status", self._on_status, 20, callback_group=self._cb)

    def _on_status(self, msg: JobStatus) -> None:
        with self._lock:
            self.statuses.append(msg)

    def wait_state(self, job_id: str, wanted: str, timeout: float = 5.0) -> JobStatus:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for st in reversed(self.statuses):
                    if st.job_id == job_id and st.state == wanted:
                        return st
            time.sleep(0.02)
        with self._lock:
            seen = [(s.job_id, s.state) for s in self.statuses if s.job_id == job_id]
        raise AssertionError(f"job={job_id} state={wanted} 타임아웃. 수신 이력={seen}")

    def call_create(self, job_id: str, plan_path: str) -> CreateJob.Response:
        assert self.create_cli.wait_for_service(timeout_sec=3.0)
        fut = self.create_cli.call_async(CreateJob.Request(job_id=job_id, plan_path=plan_path))
        deadline = time.monotonic() + 5.0
        while not fut.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert fut.done()
        return fut.result()

    def call_control(self, job_id: str, command: str, request_id: str) -> ControlJob.Response:
        assert self.control_cli.wait_for_service(timeout_sec=3.0)
        fut = self.control_cli.call_async(
            ControlJob.Request(job_id=job_id, command=command, request_id=request_id)
        )
        deadline = time.monotonic() + 5.0
        while not fut.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert fut.done()
        return fut.result()


def test_job_manager_ros2_scenarios(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ART_JOB_PLAN_ROOT", str(tmp_path))
    monkeypatch.setenv("ROS_DOMAIN_ID", "97")
    rclpy.init()

    sink = MemoryDecisionSink()
    jm = JobManagerNode(decision_sink=sink)
    fake_ctrl = FakeControllerNode()
    client = ClientHarness()

    executor = MultiThreadedExecutor(num_threads=6)
    for node in (jm, fake_ctrl, client):
        executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        # 1) 정상 완료 흐름 + SHA 전달 + Decision 발행 확인
        p1 = _make_plan(tmp_path, "JOB_OK")
        fake_ctrl.reset("normal")
        fake_ctrl.release_finish.set()
        res_ok = client.call_create("JOB_OK", p1)
        assert res_ok.accepted and res_ok.state == "QUEUED"
        st_done = client.wait_state("JOB_OK", "COMPLETED")
        assert st_done.completed_strokes == 2 and st_done.total_strokes == 2
        assert len(fake_ctrl.received_goals[-1].plan_sha256) == 64

        # 2) PAUSE -> PAUSED -> 중복/충돌 request_id -> RESUME -> DRAWING -> COMPLETED + 중복 작업 차단
        p2 = _make_plan(tmp_path, "JOB_PR")
        p_busy = _make_plan(tmp_path, "JOB_BUSY")
        fake_ctrl.reset("wait_pause_resume")
        assert client.call_create("JOB_PR", p2).accepted
        client.wait_state("JOB_PR", "DRAWING")

        # 실행 중 새 작업 거절 확인
        busy_reply = client.call_create("JOB_BUSY", p_busy)
        assert not busy_reply.accepted and busy_reply.error_code == "SYSTEM_BUSY"

        c1 = client.call_control("JOB_PR", "PAUSE", "REQ_P1")
        assert c1.accepted and c1.state == "PAUSING"
        client.wait_state("JOB_PR", "PAUSED")
        # 멱등성 & 충돌 확인
        assert client.call_control("JOB_PR", "PAUSE", "REQ_P1").accepted
        assert client.call_control("JOB_PR", "RESUME", "REQ_P1").error_code == "REQUEST_ID_CONFLICT"

        c2 = client.call_control("JOB_PR", "RESUME", "REQ_R1")
        assert c2.accepted and c2.state == "RESUMING"
        assert client.wait_state("JOB_PR", "COMPLETED").completed_strokes == 2

        # 3) CANCEL -> STOPPING -> STOPPED
        p3 = _make_plan(tmp_path, "JOB_CAN")
        fake_ctrl.reset("wait_cancel")
        assert client.call_create("JOB_CAN", p3).accepted
        client.wait_state("JOB_CAN", "DRAWING")
        c_can = client.call_control("JOB_CAN", "CANCEL", "REQ_C1")
        assert c_can.accepted and c_can.state == "STOPPING"
        client.wait_state("JOB_CAN", "STOPPED")

        # 4) 실행기 실패 시 STOPPED로 종료되고 다음 작업이 잠기지 않는지 확인
        p4 = _make_plan(tmp_path, "JOB_FAIL")
        p5 = _make_plan(tmp_path, "JOB_AFTER")
        fake_ctrl.reset("fail")
        assert client.call_create("JOB_FAIL", p4).accepted
        st_fail = client.wait_state("JOB_FAIL", "STOPPED")
        assert st_fail.error_code == "MOCK_FAIL"

        fake_ctrl.reset("normal")
        fake_ctrl.release_finish.set()
        assert client.call_create("JOB_AFTER", p5).accepted
        client.wait_state("JOB_AFTER", "COMPLETED")

        # 5) 잘못된 경로 요청 거절 확인
        bad_reply = client.call_create("JOB_BAD", "/tmp/not_allowed.json")
        assert not bad_reply.accepted

        # 6) DecisionSink에 주요 결정 이벤트들이 모두 기록되었는지 확인
        event_types = {e.event_type for e in sink.events}
        assert {"JOB_CREATED", "JOB_REJECTED", "JOB_DISPATCHED", "STROKE_COMPLETED", "CONTROL_APPLIED", "JOB_FINISHED"} <= event_types
    finally:
        executor.shutdown(timeout_sec=3.0)
        spin_thread.join(timeout=3.0)
        for node in (client, fake_ctrl, jm):
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
