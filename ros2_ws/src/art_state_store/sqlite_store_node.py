"""SQLITE_SIGNAL_CONTRACT_KR.md 규격에 따라 /art/job_decision을 구독해 SQLite에 저장하는 ROS2 노드."""

from __future__ import annotations

import os
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from .sqlite_store import RobotStateStore


def decision_qos() -> QoSProfile:
    """규격서 2장: Reliability=RELIABLE, Durability=VOLATILE, History=KEEP_LAST(100)."""
    return QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.VOLATILE,
        history=HistoryPolicy.KEEP_LAST,
        depth=100,
    )


class SqliteStoreNode(Node):
    """JobManager(/art/job_decision) 결정 이벤트를 단방향 수신해 SQLite에 기록합니다."""

    def __init__(self, *, db_path: str | Path | None = None, topic_name: str = "/art/job_decision") -> None:
        super().__init__("sqlite_store_node")
        resolved_db = Path(
            db_path or os.environ.get("ART_STATE_DB_PATH", str(Path.home() / "A4/data/art_state.db"))
        )
        self.store = RobotStateStore(resolved_db)

        from art_interfaces.msg import JobDecision  # type: ignore[attr-defined]

        self._sub = self.create_subscription(
            JobDecision,
            topic_name,
            self._on_decision,
            decision_qos(),
        )
        self.get_logger().info(
            f"sqlite_store_node 준비 완료 (topic={topic_name}, db={resolved_db})"
        )

    def _on_decision(self, msg) -> None:
        try:
            self.store.apply_job_decision(msg)
        except Exception as exc:
            self.get_logger().error(f"JobDecision SQLite 저장 실패: {exc}")

    def destroy_node(self) -> bool:
        try:
            self.store.close()
        finally:
            return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SqliteStoreNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
