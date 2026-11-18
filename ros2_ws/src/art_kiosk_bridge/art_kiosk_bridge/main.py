# [파일 역할] KioskBridge 실행 시작점
# [동작] Uvicorn 서버와 ROS 2 executor를 한 프로세스에서 실행합니다.
# [주의] ROS 2 노드는 별도 스레드에서 spin합니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Start ONE process: HTTP/Uvicorn on main thread, ROS executor on worker thread."""

from __future__ import annotations

import logging
import os
import threading

import rclpy
from rclpy.executors import SingleThreadedExecutor
import uvicorn

from .bridge_node import KioskBridgeNode
from .http_api import create_app


# [핵심 기능] 실행 진입점: 환경 변수, ROS 초기화, spin 및 종료 처리
def main() -> None:
    host = os.getenv("ART_BRIDGE_HOST", "127.0.0.1")
    port = int(os.getenv("ART_BRIDGE_PORT", "8001"))
    timeout = float(os.getenv("ART_SERVICE_TIMEOUT_SEC", "3.0"))
    if timeout <= 0 or not (1 <= port <= 65535):
        raise ValueError("ART_BRIDGE_PORT or ART_SERVICE_TIMEOUT_SEC is invalid")
    if host not in {"127.0.0.1", "localhost"}:
        logging.warning("Bridge exposed beyond loopback; TEAM_SYNC(Operations): secure access")

    rclpy.init()
    node = KioskBridgeNode(timeout_sec=timeout)
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    worker = threading.Thread(target=executor.spin, name="ros2-executor", daemon=True)
    worker.start()
    try:
        # TEAM_SYNC(Backend): FastAPI calls http://127.0.0.1:8001 (example).
        # Do not enable --reload / multiple workers: duplicate ROS nodes risk.
        app = create_app(node)
        uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info")).run()
    finally:
        executor.shutdown(timeout_sec=3.0)
        worker.join(timeout=3.0)
        executor.remove_node(node)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
