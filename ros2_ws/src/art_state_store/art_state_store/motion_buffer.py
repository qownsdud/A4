"""로봇 제어기 메모리(RAM) 상에서 고빈도 실시간 좌표·외력·웨이포인트를 관리하는 모듈.

평소 주행 중에는 디스크(SQLite)에 쓰지 않고 고정 크기 링 버퍼(deque)에만 유지하다가,
외력 감지·예외 발생 순간에만 직전 정상 복귀 웨이포인트를 추출해 DB 저장용으로 반환합니다.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import threading
import time
from typing import Any


@dataclass(frozen=True)
class MotionSample:
    """제어 루프 1틱의 목표 웨이포인트와 실제 관측 좌표·외력 스냅샷."""

    timestamp: float
    pen_idx: int
    stroke_idx: int
    point_idx: int
    held_item_name: str
    target_pose: tuple[float, ...]   # 원래 가려던 목표 좌표 [x, y, z, rx, ry, rz]
    actual_pose: tuple[float, ...]   # get_current_posx로 읽은 실제 좌표
    tool_force: tuple[float, ...]    # get_tool_force로 읽은 외력 [fx, fy, fz, tx, ty, tz]


@dataclass(frozen=True)
class RecoveryWaypoint:
    """외력 감지/중단 시 SQLite recovery_checkpoints 테이블에 저장할 복귀 정보."""

    pen_idx: int
    stroke_idx: int
    point_idx: int
    held_item_name: str
    target_pose: tuple[float, ...]
    actual_pose: tuple[float, ...]
    tool_force: tuple[float, ...]
    trigger_reason: str

    def to_db_kwargs(
        self,
        *,
        job_id: str,
        contact_pose: list[float] | tuple[float, ...] | None = None,
    ) -> dict[str, Any]:
        """RobotStateStore.save_recovery_checkpoint(**kwargs)에 바로 넘길 수 있는 dict."""
        return {
            "job_id": job_id,
            "pen_idx": self.pen_idx,
            "stroke_idx": self.stroke_idx,
            "point_idx": self.point_idx,
            "held_item_name": self.held_item_name,
            "target_pose": self.target_pose,
            "actual_pose": self.actual_pose,
            "tool_force": self.tool_force,
            "contact_pose": contact_pose,
            "trigger_reason": self.trigger_reason,
        }


def force_magnitude_n(tool_force: tuple[float, ...] | list[float]) -> float:
    """3축 병진 외력(fx, fy, fz)의 크기를 계산합니다."""
    if len(tool_force) < 3:
        return 0.0
    fx, fy, fz = float(tool_force[0]), float(tool_force[1]), float(tool_force[2])
    return math.sqrt(fx * fx + fy * fy + fz * fz)


class MotionRingBuffer:
    """고정 크기 메모리 링 버퍼(collections.deque)로 최근 주행 궤적을 보관합니다."""

    def __init__(self, maxlen: int = 100) -> None:
        if maxlen < 1:
            raise ValueError("maxlen은 1 이상이어야 합니다.")
        self._buf: deque[MotionSample] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, sample: MotionSample) -> None:
        with self._lock:
            self._buf.append(sample)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def latest(self) -> MotionSample | None:
        with self._lock:
            return self._buf[-1] if self._buf else None

    def find_last_safe_sample(self, force_limit_n: float = 15.0) -> MotionSample | None:
        """외력이 임계값 이하로 정상 주행하던 가장 최근 샘플을 뒤에서부터 찾습니다."""
        with self._lock:
            for sample in reversed(self._buf):
                if force_magnitude_n(sample.tool_force) <= force_limit_n:
                    return sample
            return self._buf[-1] if self._buf else None

    def build_recovery_waypoint(
        self,
        *,
        fault_actual_pose: tuple[float, ...] | list[float],
        fault_tool_force: tuple[float, ...] | list[float],
        force_limit_n: float = 15.0,
        trigger_reason: str = "EXTERNAL_FORCE",
    ) -> RecoveryWaypoint | None:
        """직전 정상 목표 웨이포인트와 방금 밀린 실제 좌표를 묶어 복구 객체를 만듭니다."""
        safe = self.find_last_safe_sample(force_limit_n=force_limit_n)
        if safe is None:
            return None
        return RecoveryWaypoint(
            pen_idx=safe.pen_idx,
            stroke_idx=safe.stroke_idx,
            point_idx=safe.point_idx,
            held_item_name=safe.held_item_name,
            target_pose=tuple(float(v) for v in safe.target_pose),
            actual_pose=tuple(float(v) for v in fault_actual_pose),
            tool_force=tuple(float(v) for v in fault_tool_force),
            trigger_reason=trigger_reason,
        )


class ExternalForceGuard:
    """실시간 외력 감지와 링 버퍼 기록을 함께 담당하는 헬퍼."""

    def __init__(self, *, force_limit_n: float = 15.0, buffer_maxlen: int = 100) -> None:
        self.force_limit_n = float(force_limit_n)
        self.buffer = MotionRingBuffer(maxlen=buffer_maxlen)

    def record_tick(
        self,
        *,
        pen_idx: int,
        stroke_idx: int,
        point_idx: int,
        held_item_name: str,
        target_pose: tuple[float, ...] | list[float],
        actual_pose: tuple[float, ...] | list[float],
        tool_force: tuple[float, ...] | list[float],
    ) -> bool:
        """1틱 데이터를 버퍼에 기록하고 외력 초과 여부(True=이상 감지)를 반환합니다."""
        sample = MotionSample(
            timestamp=time.monotonic(),
            pen_idx=pen_idx,
            stroke_idx=stroke_idx,
            point_idx=point_idx,
            held_item_name=held_item_name,
            target_pose=tuple(float(v) for v in target_pose),
            actual_pose=tuple(float(v) for v in actual_pose),
            tool_force=tuple(float(v) for v in tool_force),
        )
        exceeded = force_magnitude_n(sample.tool_force) > self.force_limit_n
        if not exceeded:
            self.buffer.push(sample)
        return exceeded
