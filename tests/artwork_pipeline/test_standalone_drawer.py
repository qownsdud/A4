"""StandaloneDrawerNode가 drawing_plan.json을 draw_image_standalone.py 형식으로 변환·실행하는지 검증합니다."""

import json
import sys
import time
from pathlib import Path

import rclpy
from rclpy.executors import SingleThreadedExecutor

from art_artwork_pipeline.path_planner.drawing_plan import build_plan, write_job_plan
from art_artwork_pipeline.standalone_drawer import StandaloneDrawerNode, plan_to_standalone_strokes
from art_interfaces.msg import JobStatus
from art_interfaces.srv import CreateJob


def test_plan_to_standalone_strokes_and_node_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("ART_JOB_PLAN_ROOT", str(tmp_path))
    job_id = "JOB_STANDALONE_TEST_01"
    plan = build_plan(
        [
            {"points": [[10, 10], [50, 50], [90, 20]]},
            {"points": [[20, 80], [80, 80]]},
        ],
        100,
        100,
        job_id=job_id,
        seed=1,
    )
    plan_path = Path(write_job_plan(plan, plan_root=tmp_path))

    # 1. strokes_px 변환 검증
    out_strokes = plan_path.parent / "standalone_strokes.json"
    count = plan_to_standalone_strokes(plan_path, out_strokes)
    assert count == len(plan["strokes"])
    converted = json.loads(out_strokes.read_text(encoding="utf-8"))
    assert len(converted["strokes_px"]) == count
    assert converted["strokes_px"][0] == plan["strokes"][0]["points_mm"]

    # 실제 제어 세션을 사용하지만 모션은 시험 관측기로 치환한 프로세스입니다.
    fake_script=Path(__file__).parents[1]/'robot_worker_fixture.py'
    settings=tmp_path/'motion.json'
    settings.write_text(json.dumps(dict(validated=True,force_limits=[10.]*6,force_bias=[0.]*6)))
    monkeypatch.setenv('ART_MOTION_CONTROL_CONFIG',str(settings))
    monkeypatch.setenv('ART_STANDALONE_SCRIPT',str(fake_script))
    monkeypatch.setenv('ART_WS_DSR_SETUP',str(tmp_path/'absent.bash'))
    rclpy.init()
    node = StandaloneDrawerNode()
    client_node = rclpy.create_node("standalone_drawer_test_client")
    statuses: list[JobStatus] = []
    client_node.create_subscription(JobStatus, "/art/job_status", statuses.append, 10)
    cli = client_node.create_client(CreateJob, "/art/create_job")

    executor = SingleThreadedExecutor()
    executor.add_node(node)
    executor.add_node(client_node)
    try:
        assert cli.wait_for_service(timeout_sec=3.0)
        req = CreateJob.Request(job_id=job_id, plan_path=str(plan_path))
        fut = cli.call_async(req)
        deadline = time.monotonic() + 3.0
        while not fut.done() and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.05)
        assert fut.done()
        resp = fut.result()
        assert resp.accepted is True
        assert resp.job_id == job_id

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.05)
            if any(s.job_id == job_id and s.state == "COMPLETED" for s in statuses):
                break
        assert any(s.job_id == job_id and s.state == "COMPLETED" for s in statuses)
    finally:
        executor.shutdown()
        client_node.destroy_node()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
