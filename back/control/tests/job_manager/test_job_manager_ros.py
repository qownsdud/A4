# [파일 역할] 이전 JobManager/ROS 연동 테스트
# [동작] 구형 시뮬레이션 상태 머신 및 Bridge ROS 계약의 회귀를 검사합니다.
# [주의] ROS 2가 없는 환경에서는 일부 자동 건너뛸 수 있습니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Actual ROS2 service/topic contract test; skips without rclpy/art_interfaces.

Uses unique service names and only a simulation-only manager; no robot commands.
"""
import asyncio
import threading
import uuid

import pytest

rclpy = pytest.importorskip('rclpy')
pytest.importorskip('art_interfaces.srv')
pytest.importorskip('art_kiosk_bridge.bridge_node')
from rclpy.executors import SingleThreadedExecutor
from art_kiosk_bridge.bridge_node import KioskBridgeNode
from art_job_manager.job_manager_test_node import JobManagerNode

from test_job_engine import plan


# [핵심 기능] pytest: real job manager ros bridge contract 조건을 검증
def test_real_job_manager_ros_bridge_contract(tmp_path):
    rclpy.init()
    prefix = f'/jobmgr_{uuid.uuid4().hex[:9]}'
    root = tmp_path / 'plans'
    root.mkdir()
    file = plan(root, 'JROS', count=60)
    manager = JobManagerNode(db_path=tmp_path / 'jobs.db', plan_root=root, simulation=True,
                             create_service=f'{prefix}/create', control_service=f'{prefix}/control',
                             status_topic=f'{prefix}/status', sim_period=0.5)
    bridge = KioskBridgeNode(create_service=f'{prefix}/create', control_service=f'{prefix}/control',
                             status_topic=f'{prefix}/status', timeout_sec=3.0)
    executor = SingleThreadedExecutor()
    executor.add_node(manager)
    executor.add_node(bridge)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    try:
        async def check():
            for _ in range(100):
                if bridge.is_ready():
                    break
                await asyncio.sleep(0.02)
            assert bridge.is_ready()
            created = await bridge.create_job('JROS', file)
            assert created.accepted and created.manager_state == 'DRAWING'
            paused = await bridge.control_job('JROS', 'PAUSE', 'pause1')
            assert paused.accepted and paused.manager_state == 'PAUSING'
            for _ in range(130):
                status = bridge.get_status('JROS')
                if status and status.state == 'PAUSED':
                    return
                await asyncio.sleep(0.02)
            pytest.fail('Expected a confirmed (simulated) PAUSED status')
        asyncio.run(check())
    finally:
        executor.shutdown(timeout_sec=3.0)
        thread.join(timeout=3.0)
        executor.remove_node(bridge)
        executor.remove_node(manager)
        bridge.destroy_node()
        manager.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
