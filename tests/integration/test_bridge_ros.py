# [파일 역할] KioskBridge 통합 회귀 테스트
# [동작] HTTP→ROS 계약, 상태 캐시, 오류 처리, 정지·복구 시나리오를 자동 검증합니다.
# [주의] 테스트를 실행한다고 실제 로봇이 움직이지 않습니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""ROS 2 integration tests; skipped when Jazzy/rclpy/art_interfaces are absent."""

import asyncio
import threading
import uuid

import pytest

rclpy = pytest.importorskip("rclpy")
pytest.importorskip("art_interfaces.srv")
from rclpy.executors import SingleThreadedExecutor
from art_kiosk_bridge.bridge_node import KioskBridgeNode
from art_kiosk_bridge.errors import ServiceUnavailable
from mocks.mock_job_manager import MockJobManager


# [핵심 기능] pytest: ros service and confirmed topic 조건을 검증
def test_ros_service_and_confirmed_topic():
    rclpy.init()
    prefix = f"/test_{uuid.uuid4().hex[:9]}"
    # TEAM_SYNC: test-specific service names avoid collision with a real robot.
    mock = MockJobManager(create_service=f"{prefix}/create", control_service=f"{prefix}/control",
                          status_topic=f"{prefix}/status", progress_period_sec=0.3, total_strokes=100)
    bridge = KioskBridgeNode(create_service=f"{prefix}/create", control_service=f"{prefix}/control",
                             status_topic=f"{prefix}/status", timeout_sec=2.0)
    executor = SingleThreadedExecutor()
    executor.add_node(mock)
    executor.add_node(bridge)
    worker = threading.Thread(target=executor.spin, daemon=True)
    worker.start()
    try:
        async def check():
            for _ in range(100):
                if bridge.is_ready():
                    break
                await asyncio.sleep(0.02)
            assert bridge.is_ready()
            response = await bridge.create_job("JOB_ROS", "/tmp/plan.json")
            assert response.accepted and response.job_id == "JOB_ROS"
            reply = await bridge.control_job("JOB_ROS", "PAUSE", "request01")
            assert reply.manager_state == "PAUSING"
            for _ in range(100):
                snapshot = bridge.get_status("JOB_ROS")
                if snapshot and snapshot.state == "PAUSED":
                    return
                await asyncio.sleep(0.02)
            pytest.fail("PAUSED topic event not received")
        asyncio.run(check())
    finally:
        executor.shutdown(timeout_sec=3.0)
        worker.join(timeout=3.0)
        executor.remove_node(bridge)
        executor.remove_node(mock)
        bridge.destroy_node()
        mock.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


# [핵심 기능] pytest: service unavailable is explicit 조건을 검증
def test_service_unavailable_is_explicit():
    rclpy.init()
    prefix = f"/absent_{uuid.uuid4().hex[:9]}"
    bridge = KioskBridgeNode(create_service=f"{prefix}/create", control_service=f"{prefix}/control")
    try:
        with pytest.raises(ServiceUnavailable):
            asyncio.run(bridge.create_job("MISSING", "/tmp/missing.json"))
    finally:
        bridge.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
