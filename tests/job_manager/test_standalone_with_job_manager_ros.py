"""JobManagerNode(+art_state_store SQLite)와 StandaloneDrawingControllerNode의 ROS2 연동을 검증합니다."""

import json
import sqlite3
import time
from pathlib import Path

import rclpy
from rclpy.executors import MultiThreadedExecutor

from art_drawing_controller.standalone_executor import StandaloneDrawingControllerNode
from art_interfaces.msg import JobStatus
from art_interfaces.srv import CreateJob
from art_job_manager.job_manager_node import JobManagerNode


def _make_plan(plan_root: Path, job_id: str) -> Path:
    job_dir = plan_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema_version": "0.2",
        "job_id": job_id,
        "unit": "mm",
        "coordinate_frame": "paper_top_left_x_right_y_down",
        "paper_mm": {"width": 297, "height": 210},
        "strokes": [
            {"stroke_id": 1, "pen_id": "PEN_1", "points_mm": [[10.0, 10.0], [30.0, 20.0]]},
            {"stroke_id": 2, "pen_id": "PEN_2", "points_mm": [[40.0, 40.0], [70.0, 60.0]]},
            {"stroke_id": 3, "pen_id": "PEN_3", "points_mm": [[80.0, 80.0], [100.0, 90.0]]},
        ],
    }
    path = job_dir / "drawing_plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def test_job_manager_sqlite_and_standalone_controller_ros(monkeypatch, tmp_path):
    plan_root = tmp_path / "jobs"
    db_path = tmp_path / "art_state.db"
    job_id = "JOB_STANDALONE_JM_01"
    plan_path = _make_plan(plan_root, job_id)

    fake_script = tmp_path / "fake_standalone.py"
    fake_script.write_text(
        "import sys, time\n"
        "print('[펜 1] 진행 1/1 획', flush=True)\n"
        "time.sleep(0.02)\n"
        "print('[펜 2] 진행 1/1 획', flush=True)\n"
        "time.sleep(0.02)\n"
        "print('[펜 3] 진행 1/1 획', flush=True)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("ART_JOB_PLAN_ROOT", str(plan_root))
    monkeypatch.setenv("ART_STATE_DB_PATH", str(db_path))
    monkeypatch.setenv("ART_STANDALONE_SCRIPT", str(fake_script))
    monkeypatch.setenv("ART_WS_DSR_SETUP", str(tmp_path / "no_setup.bash"))

    rclpy.init()
    jm_node = JobManagerNode()
    ctrl_node = StandaloneDrawingControllerNode()
    client_node = rclpy.create_node("standalone_jm_test_client")
    statuses: list[JobStatus] = []
    client_node.create_subscription(JobStatus, "/art/job_status", statuses.append, 10)
    create_cli = client_node.create_client(CreateJob, "/art/create_job")

    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(jm_node)
    executor.add_node(ctrl_node)
    executor.add_node(client_node)
    spin_thread = __import__("threading").Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        assert create_cli.wait_for_service(timeout_sec=3.0)
        fut = create_cli.call_async(CreateJob.Request(job_id=job_id, plan_path=str(plan_path)))
        deadline = time.monotonic() + 3.0
        while not fut.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert fut.done()
        resp = fut.result()
        assert resp.accepted is True

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if any(s.job_id == job_id and s.state == "COMPLETED" for s in statuses):
                break
            time.sleep(0.02)
        assert any(s.job_id == job_id and s.state == "COMPLETED" and s.completed_strokes == 3 for s in statuses)

        # standalone_strokes.json 생성 확인
        strokes_file = plan_path.parent / "standalone_strokes.json"
        assert strokes_file.is_file()
        assert len(json.loads(strokes_file.read_text(encoding="utf-8"))["strokes_px"]) == 3
    finally:
        executor.shutdown()
        spin_thread.join(timeout=1.0)
        client_node.destroy_node()
        ctrl_node.destroy_node()
        jm_node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    # SQLite DB 기록 검증
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT state, completed_strokes, total_strokes FROM jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        assert row == ("COMPLETED", 3, 3)
        events = [
            r[0]
            for r in conn.execute(
                "SELECT event_type FROM job_events WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        ]
        assert "JOB_CREATED" in events
        assert "JOB_DISPATCHED" in events
        assert "STATE_CHANGED" in events
        assert events.count("STROKE_COMPLETED") == 3
        assert "JOB_FINISHED" in events
    finally:
        conn.close()
