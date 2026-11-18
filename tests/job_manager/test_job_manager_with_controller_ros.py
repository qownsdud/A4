"""JobManagerNode <-> 실제 DrawingNode 간 ROS2 ExecuteDrawing + ControlDrawing(PAUSE/RESUME) 연동 테스트."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

rclpy = pytest.importorskip("rclpy")
from rclpy.executors import MultiThreadedExecutor

from art_drawing_controller.drawing_node import DrawingNode
from art_job_manager.decision_port import MemoryDecisionSink
from art_job_manager.job_manager_node import JobManagerNode
from tests.job_manager.test_job_manager_ros import ClientHarness, _make_plan


class MockDoosanAdapter:
    """DrawingNode에 주입하는 모의 어댑터입니다."""

    def __init__(self, _node, settings) -> None:
        self.settings = settings
        self.held_pen = None
        self.pose = [0.0, 0.0, float(settings["travel_z_mm"]), 0.0, 180.0, 0.0]
        self.pending = None
        self.paused = False
        self.progress = 0
        self.outputs = {}
        self.control = None

    def require_ready(self):
        pass

    def preflight(self):
        pass

    def validate(self, pose):
        return list(pose)

    def at_pose(self, target):
        return self.pose == list(target)

    def current_pose(self):
        return list(self.pose)

    def set_output(self, index, value):
        self.outputs[index] = value

    def begin_motion(self, poses, velocity, acceleration=None, mod=0):
        self.pending = list(poses[-1])
        self.progress = 0

    def motion_complete(self):
        if self.paused:
            return False
        self.progress += 1
        if self.progress < 5:
            return False
        if self.pending is not None:
            self.pose = list(self.pending)
        return True

    def pause(self, inflight):
        self.paused = True
        return tuple(self.pose)

    def resume(self, hold, inflight):
        self.paused = False

    def stop(self):
        self.paused = False
        self.pose[2] = float(self.settings["travel_z_mm"])
        return True

    def pen_up_confirmed(self):
        return True


def test_job_manager_and_drawing_controller_pause_resume_complete(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ART_JOB_PLAN_ROOT", str(tmp_path))
    monkeypatch.setenv("ROS_DOMAIN_ID", "97")
    rclpy.init()

    sink = MemoryDecisionSink()
    jm = JobManagerNode(decision_sink=sink)
    dc = DrawingNode(adapter_factory=MockDoosanAdapter)
    dc.plan_root = tmp_path
    client = ClientHarness()

    executor = MultiThreadedExecutor(num_threads=6)
    for node in (jm, dc, client):
        executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        plan_path = _make_plan(tmp_path, "JOB_CTRL_1", stroke_count=2)
        assert client.call_create("JOB_CTRL_1", plan_path).accepted
        client.wait_state("JOB_CTRL_1", "DRAWING", timeout=5.0)

        # 일시정지 -> PAUSED 확인 -> 재개 -> COMPLETED 확인
        c_pause = client.call_control("JOB_CTRL_1", "PAUSE", "REQ_PAUSE_1")
        assert c_pause.accepted and c_pause.state == "PAUSING"
        client.wait_state("JOB_CTRL_1", "PAUSED", timeout=5.0)

        c_resume = client.call_control("JOB_CTRL_1", "RESUME", "REQ_RESUME_1")
        assert c_resume.accepted and c_resume.state == "RESUMING"
        done = client.wait_state("JOB_CTRL_1", "COMPLETED", timeout=15.0)
        assert done.completed_strokes == 2 and done.total_strokes == 2
        assert any(e.event_type == "JOB_FINISHED" and e.state == "COMPLETED" for e in sink.events)
    finally:
        executor.shutdown(timeout_sec=3.0)
        spin_thread.join(timeout=3.0)
        for node in (client, dc, jm):
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
