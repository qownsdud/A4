"""JobManager의 결정을 외부 저장소(향후 SQLite 모듈 등)로 단방향 전달하는 포트입니다."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class JobDecision:
    """JobManager가 내린 단일 제어·상태 결정 이벤트입니다."""

    event_type: str
    job_id: str
    state: str
    completed_strokes: int = 0
    total_strokes: int = 0
    current_pen: str = ""
    plan_path: str = ""
    plan_sha256: str = ""
    command: str = ""
    request_id: str = ""
    error_code: str = ""
    message: str = ""
    occurred_at: float = field(default_factory=time.time)


class DecisionSink(Protocol):
    """결정 이벤트를 수신하는 단방향 포트 인터페이스입니다."""

    def emit(self, decision: JobDecision) -> None:
        """결정 이벤트를 전달합니다. JobManager는 반환값을 기다리지 않습니다."""


class LoggingDecisionSink:
    """SQLite 신호 규약 확정 전 기본으로 사용하는 로깅 전용 Sink입니다."""

    def __init__(self, logger=None) -> None:
        self._logger = logger or logging.getLogger("art_job_manager.decision")

    def emit(self, decision: JobDecision) -> None:
        msg = (
            f"[Decision] type={decision.event_type} job={decision.job_id} "
            f"state={decision.state} strokes={decision.completed_strokes}/{decision.total_strokes}"
        )
        if decision.error_code:
            msg += f" err={decision.error_code}"
        if hasattr(self._logger, "info"):
            self._logger.info(msg)


class MemoryDecisionSink:
    """단위 테스트에서 결정 발행 순서와 내용을 검증하기 위한 메모리 Sink입니다."""

    def __init__(self) -> None:
        self.events: list[JobDecision] = []

    def emit(self, decision: JobDecision) -> None:
        self.events.append(decision)
