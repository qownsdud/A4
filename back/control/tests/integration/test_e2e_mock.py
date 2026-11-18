# [파일 역할] KioskBridge 통합 회귀 테스트
# [동작] HTTP→ROS 계약, 상태 캐시, 오류 처리, 정지·복구 시나리오를 자동 검증합니다.
# [주의] 테스트를 실행한다고 실제 로봇이 움직이지 않습니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Real ROS Mock + actual HTTP ASGI bridge, no M0609 or RG2 hardware."""

import asyncio
import threading
import uuid

import httpx
import pytest

rclpy = pytest.importorskip("rclpy")
pytest.importorskip("art_interfaces.srv")
from rclpy.executors import SingleThreadedExecutor
from art_kiosk_bridge.bridge_node import KioskBridgeNode
from art_kiosk_bridge.http_api import create_app
from mocks.mock_job_manager import MockJobManager


# [핵심 기능] pytest: http ros mock end to end 조건을 검증
def test_http_ros_mock_end_to_end():
    rclpy.init()
    prefix = f"/e2e_{uuid.uuid4().hex[:9]}"
    mock = MockJobManager(create_service=f"{prefix}/create", control_service=f"{prefix}/control",
                          status_topic=f"{prefix}/status", progress_period_sec=0.3, total_strokes=100)
    bridge = KioskBridgeNode(create_service=f"{prefix}/create", control_service=f"{prefix}/control",
                             status_topic=f"{prefix}/status")
    executor = SingleThreadedExecutor()
    executor.add_node(mock)
    executor.add_node(bridge)
    worker = threading.Thread(target=executor.spin, daemon=True)
    worker.start()
    try:
        async def exercise():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(bridge)),
                                         base_url="http://mock.local") as client:
                for _ in range(100):
                    if bridge.is_ready():
                        break
                    await asyncio.sleep(0.02)
                reply = await client.post("/bridge/jobs", json={"job_id": "J100", "plan_path": "/tmp/J100.json"})
                assert reply.status_code == 202
                duplicate = await client.post("/bridge/jobs", json={"job_id": "J100", "plan_path": "/tmp/J100.json"})
                assert duplicate.status_code == 409
                pause = await client.post("/bridge/jobs/J100/control", json={"command": "PAUSE", "request_id": "P100"})
                assert pause.status_code == 202 and pause.json()["manager_state"] == "PAUSING"
                for _ in range(100):
                    got = await client.get("/bridge/jobs/J100")
                    if got.status_code == 200 and got.json()["state"] == "PAUSED":
                        break
                    await asyncio.sleep(0.02)
                else:
                    pytest.fail("Never saw a confirmed mock PAUSED status")
                resume = await client.post("/bridge/jobs/J100/control", json={"command": "RESUME", "request_id": "R100"})
                assert resume.status_code == 202 and resume.json()["manager_state"] == "DRAWING"
        asyncio.run(exercise())
    finally:
        executor.shutdown(timeout_sec=3.0)
        worker.join(timeout=3.0)
        executor.remove_node(bridge)
        executor.remove_node(mock)
        bridge.destroy_node()
        mock.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
