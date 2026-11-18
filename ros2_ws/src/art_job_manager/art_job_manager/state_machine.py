"""SQLite와 분리된 순수 인메모리 JobManager 상태 머신입니다."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from .decision_port import DecisionSink, JobDecision, LoggingDecisionSink
from .plan_validator import PlanError, default_plan_root, load_plan

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_ACTIVE_STATES = frozenset(
    {"QUEUED", "DISPATCHING", "DRAWING", "PAUSING", "PAUSED", "RESUMING", "STOPPING"}
)
_TERMINAL_STATES = frozenset({"COMPLETED", "STOPPED"})


@dataclass(frozen=True)
class CommandReply:
    """CreateJob / ControlJob 요청 처리 결과입니다."""

    accepted: bool
    job_id: str
    state: str
    error_code: str = ""
    message: str = ""


@dataclass(frozen=True)
class DispatchRequest:
    """실행기로 보낼 ExecuteDrawing Goal 파라미터입니다."""

    job_id: str
    plan_path: str
    plan_sha256: str
    start_stroke_id: int


@dataclass
class JobSnapshot:
    """현재 작업의 인메모리 스냅샷입니다."""

    job_id: str
    plan_path: str
    plan_sha256: str
    state: str
    total_strokes: int
    completed_strokes: int = 0
    current_pen: str = "PEN_1"
    error_code: str = ""
    message: str = ""
    live_execution: bool = False
    started_at: float = 0.0
    updated_at: float = 0.0


class JobStateMachine:
    """단일 활성 작업을 인메모리로 제어하고 결정 이벤트를 단방향 발행합니다."""

    def __init__(
        self,
        *,
        plan_root: Path | None = None,
        decision_sink: DecisionSink | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._plan_root = plan_root if plan_root is not None else default_plan_root()
        self._sink: DecisionSink = decision_sink or LoggingDecisionSink()
        self._jobs: dict[str, JobSnapshot] = {}
        self._pens: dict[str, tuple[str, ...]] = {}
        self._receipts: dict[tuple[str, str], tuple[str, CommandReply]] = {}
        self._active_job_id: str | None = None

    def _emit(
        self,
        event_type: str,
        snap: JobSnapshot | None = None,
        *,
        job_id: str = "",
        state: str = "",
        command: str = "",
        request_id: str = "",
        error_code: str = "",
        message: str = "",
    ) -> None:
        if snap is not None:
            decision = JobDecision(
                event_type=event_type,
                job_id=snap.job_id,
                state=snap.state,
                completed_strokes=snap.completed_strokes,
                total_strokes=snap.total_strokes,
                current_pen=snap.current_pen,
                plan_path=snap.plan_path,
                plan_sha256=snap.plan_sha256,
                command=command,
                request_id=request_id,
                error_code=error_code or snap.error_code,
                message=message or snap.message,
            )
        else:
            decision = JobDecision(
                event_type=event_type,
                job_id=job_id,
                state=state,
                command=command,
                request_id=request_id,
                error_code=error_code,
                message=message,
            )
        self._sink.emit(decision)

    def status(self, job_id: str) -> JobSnapshot | None:
        with self._lock:
            snap = self._jobs.get(job_id)
            return replace(snap) if snap is not None else None

    def active_job(self) -> JobSnapshot | None:
        with self._lock:
            if not self._active_job_id:
                return None
            snap = self._jobs.get(self._active_job_id)
            return replace(snap) if snap is not None else None

    def create_job(self, job_id: str, plan_path: str) -> CommandReply:
        if not _ID_PATTERN.fullmatch(job_id):
            self._emit("JOB_REJECTED", job_id=job_id, state="REJECTED", error_code="INVALID_JOB_ID")
            return CommandReply(False, job_id, "REJECTED", "INVALID_JOB_ID", "유효하지 않은 작업 ID입니다.")

        with self._lock:
            if job_id in self._jobs:
                existing = self._jobs[job_id]
                self._emit("JOB_REJECTED", existing, error_code="DUPLICATE_JOB")
                return CommandReply(False, job_id, existing.state, "DUPLICATE_JOB", "이미 등록된 작업 ID입니다.")

            if self._active_job_id and self._jobs[self._active_job_id].state in _ACTIVE_STATES:
                active = self._active_job_id
                self._emit(
                    "JOB_REJECTED",
                    job_id=job_id,
                    state="REJECTED",
                    error_code="SYSTEM_BUSY",
                    message=f"Active job: {active}",
                )
                return CommandReply(False, job_id, "REJECTED", "SYSTEM_BUSY", f"실행 중인 작업이 있습니다: {active}")

            try:
                summary = load_plan(job_id, plan_path, plan_root=self._plan_root)
            except PlanError as exc:
                code = str(exc)
                self._emit("JOB_REJECTED", job_id=job_id, state="REJECTED", error_code=code)
                return CommandReply(False, job_id, "REJECTED", code, f"계획 검증 실패: {code}")

            now = time.time()
            snap = JobSnapshot(
                job_id=job_id,
                plan_path=summary.path,
                plan_sha256=summary.sha256,
                state="QUEUED",
                total_strokes=summary.stroke_count,
                current_pen=summary.pen_ids[0],
                message="작업 등록 완료; 실행 대기 중",
                started_at=now,
                updated_at=now,
            )
            self._jobs[job_id] = snap
            self._pens[job_id] = summary.pen_ids
            self._active_job_id = job_id
            self._emit("JOB_CREATED", snap)
            return CommandReply(True, job_id, "QUEUED", "", snap.message)

    def prepare_dispatch(self, job_id: str) -> DispatchRequest | None:
        with self._lock:
            snap = self._jobs.get(job_id)
            if snap is None or snap.state != "QUEUED":
                return None
            try:
                summary = load_plan(job_id, snap.plan_path, plan_root=self._plan_root)
            except PlanError as exc:
                self._finish(snap, "STOPPED", str(exc), f"실행 전 계획 접근 실패: {exc}")
                return None

            if summary.sha256 != snap.plan_sha256 or summary.stroke_count != snap.total_strokes:
                self._finish(snap, "STOPPED", "PLAN_CHANGED", "DrawingPlan이 변경되어 실행을 중단합니다.")
                return None

            snap.state = "DISPATCHING"
            snap.error_code = ""
            snap.message = "실행기로 그리기 시작 요청 전송"
            snap.updated_at = time.time()
            self._emit("JOB_DISPATCHED", snap)
            return DispatchRequest(
                job_id=job_id,
                plan_path=snap.plan_path,
                plan_sha256=snap.plan_sha256,
                start_stroke_id=snap.completed_strokes + 1,
            )

    def on_feedback(
        self,
        job_id: str,
        *,
        event: str,
        stroke_id: int = 0,
        pen_id: str = "",
        pen_up_confirmed: bool = False,
        message: str = "",
    ) -> bool:
        with self._lock:
            snap = self._jobs.get(job_id)
            if snap is None or snap.state in _TERMINAL_STATES:
                return False

            now = time.time()
            if event in ("STARTED", "STARTED_LIVE"):
                snap.live_execution = event == "STARTED_LIVE"
                if snap.state in ("DISPATCHING", "RESUMING"):
                    snap.state = "DRAWING"
                    snap.message = message or "로봇 그리기를 진행 중입니다."
                    snap.updated_at = now
                    self._emit("STATE_CHANGED", snap)
                return True

            if event == "STROKE_STARTED":
                if pen_id:
                    snap.current_pen = pen_id
                snap.message = message or f"획 {stroke_id} 수행 중"
                snap.updated_at = now
                return True

            if event == "STROKE_COMPLETED":
                if not pen_up_confirmed:
                    return False
                if stroke_id != snap.completed_strokes + 1 or stroke_id > snap.total_strokes:
                    return False
                snap.completed_strokes = stroke_id
                pens = self._pens.get(job_id, ())
                if stroke_id < len(pens):
                    snap.current_pen = pens[stroke_id]
                elif pen_id:
                    snap.current_pen = pen_id
                snap.message = message or f"획 {stroke_id}/{snap.total_strokes} 완료"
                snap.updated_at = now
                self._emit("STROKE_COMPLETED", snap)
                return True

            return False

    def control_job(self, job_id: str, command: str, request_id: str) -> CommandReply:
        cmd = (command or "").strip().upper()
        if not _ID_PATTERN.fullmatch(job_id) or not _ID_PATTERN.fullmatch(request_id):
            return CommandReply(False, job_id, "UNKNOWN", "INVALID_ID", "유효하지 않은 ID입니다.")

        with self._lock:
            receipt = self._receipts.get((job_id, request_id))
            if receipt is not None:
                prev_cmd, prev_reply = receipt
                if prev_cmd == cmd:
                    return prev_reply
                return CommandReply(False, job_id, prev_reply.state, "REQUEST_ID_CONFLICT", "동일 request_id로 다른 명령이 요청되었습니다.")

            snap = self._jobs.get(job_id)
            if snap is None:
                reply = CommandReply(False, job_id, "UNKNOWN", "JOB_NOT_FOUND", "작업을 찾을 수 없습니다.")
                self._receipts[(job_id, request_id)] = (cmd, reply)
                return reply

            if cmd not in ("PAUSE", "RESUME", "CANCEL"):
                reply = CommandReply(False, job_id, snap.state, "UNKNOWN_COMMAND", f"지원하지 않는 명령: {cmd}")
                self._receipts[(job_id, request_id)] = (cmd, reply)
                return reply

            reply = self._apply_control(snap, cmd)
            self._receipts[(job_id, request_id)] = (cmd, reply)
            self._emit(
                "CONTROL_REQUESTED",
                snap,
                command=cmd,
                request_id=request_id,
                error_code=reply.error_code,
                message=reply.message,
            )
            return reply

    def _apply_control(self, snap: JobSnapshot, cmd: str) -> CommandReply:
        now = time.time()
        if cmd == "PAUSE":
            if snap.state != "DRAWING":
                return CommandReply(False, snap.job_id, snap.state, "INVALID_TRANSITION", "그리기 중에만 일시정지할 수 있습니다.")
            snap.state = "PAUSING"
            snap.message = "일시정지 요청 전달 중"
            snap.updated_at = now
            return CommandReply(True, snap.job_id, "PAUSING", "", snap.message)

        if cmd == "RESUME":
            if snap.state != "PAUSED":
                return CommandReply(False, snap.job_id, snap.state, "INVALID_TRANSITION", "일시정지 상태에서만 재개할 수 있습니다.")
            snap.state = "RESUMING"
            snap.message = "재개 요청 전달 중"
            snap.updated_at = now
            return CommandReply(True, snap.job_id, "RESUMING", "", snap.message)

        # CANCEL
        if snap.state in _TERMINAL_STATES:
            return CommandReply(True, snap.job_id, snap.state, "", "이미 종료된 작업입니다.")
        if snap.state == "QUEUED":
            self._finish(snap, "STOPPED", "CANCELED", "실행 전 취소되었습니다.")
            return CommandReply(True, snap.job_id, "STOPPED", "", snap.message)

        snap.state = "STOPPING"
        snap.message = "작업 중단 요청 전달 중"
        snap.updated_at = now
        return CommandReply(True, snap.job_id, "STOPPING", "", snap.message)

    def on_control_reply(
        self,
        job_id: str,
        command: str,
        accepted: bool,
        *,
        error_code: str = "",
        message: str = "",
    ) -> None:
        with self._lock:
            snap = self._jobs.get(job_id)
            if snap is None or snap.state in _TERMINAL_STATES:
                return
            now = time.time()
            if command == "PAUSE" and snap.state == "PAUSING":
                snap.state = "PAUSED" if accepted else "DRAWING"
                snap.error_code = "" if accepted else (error_code or "PAUSE_REJECTED")
                snap.message = message or ("일시정지 확인됨" if accepted else "일시정지 요청이 거절되었습니다.")
                snap.updated_at = now
                self._emit("CONTROL_APPLIED", snap, command=command)
            elif command == "RESUME" and snap.state == "RESUMING":
                snap.state = "DRAWING" if accepted else "PAUSED"
                snap.error_code = "" if accepted else (error_code or "RESUME_REJECTED")
                snap.message = message or ("재개 확인됨" if accepted else "재개 요청이 거절되었습니다.")
                snap.updated_at = now
                self._emit("CONTROL_APPLIED", snap, command=command)

    def on_action_result(
        self,
        job_id: str,
        *,
        ros_status: int,
        success: bool,
        final_state: str,
        completed_strokes: int,
        pen_up_confirmed: bool,
        error_code: str = "",
        message: str = "",
    ) -> bool:
        with self._lock:
            snap = self._jobs.get(job_id)
            if snap is None or snap.state in _TERMINAL_STATES:
                return False

            if (
                ros_status == 4
                and success
                and final_state == "COMPLETED"
                and completed_strokes == snap.total_strokes
                and pen_up_confirmed
            ):
                self._finish(snap, "COMPLETED", "", "드로잉이 정상 완료되었습니다.")
                return True

            if snap.state == "STOPPING" and final_state == "INTERRUPTED_SAFE" and pen_up_confirmed:
                self._finish(snap, "STOPPED", "", "안전 중단 및 펜 이격 확인 완료")
                return True

            self._finish(
                snap,
                "STOPPED",
                error_code or "ACTION_FAILED",
                message or f"작업 종료 (ros={ros_status}, final={final_state})",
            )
            return False

    def mark_failed(self, job_id: str, error_code: str, message: str) -> bool:
        with self._lock:
            snap = self._jobs.get(job_id)
            if snap is None or snap.state in _TERMINAL_STATES:
                return False
            self._finish(snap, "STOPPED", error_code, message)
            return True

    def _finish(self, snap: JobSnapshot, state: str, error_code: str, message: str) -> None:
        snap.state = state
        snap.error_code = error_code[:64]
        snap.message = message[:480]
        snap.updated_at = time.time()
        if self._active_job_id == snap.job_id:
            self._active_job_id = None
        self._emit("JOB_FINISHED", snap)
