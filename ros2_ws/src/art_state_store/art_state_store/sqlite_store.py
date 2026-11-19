"""A4 드로잉 시스템용 독립 SQLite 영속 저장소 모듈."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any


SCHEMA_PATH = Path(__file__).resolve().with_name("schema.sql")

_ALLOWED_JOB_FIELDS = {
    "strokes_path",
    "state",
    "completed_strokes",
    "resume_stroke_id",
    "current_pen",
    "exit_code",
    "error_code",
    "message",
    "started_at",
    "ended_at",
}


class RobotStateStore:
    """작업 상태, 명령 멱등성, 캘리브레이션, 복구 웨이포인트를 관리하는 SQLite 저장소."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with self.transaction() as conn:
            conn.executescript(schema_sql)

    @contextmanager
    def transaction(self):
        with self._lock:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                yield self.conn
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ------------------------------------------------------------------
    # 작업(jobs) 관리
    # ------------------------------------------------------------------
    def create_job(
        self,
        *,
        job_id: str,
        plan_path: str,
        plan_sha256: str,
        total_strokes: int,
        strokes_path: str = "",
        state: str = "DISPATCHING",
        current_pen: str = "PEN_1",
        virtual: bool = False,
        dry_run: bool = False,
        skip_cal: bool = False,
        message: str = "",
    ) -> None:
        now = time.time()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, plan_path, strokes_path, plan_sha256, state,
                    total_strokes, current_pen, virtual, dry_run, skip_cal,
                    message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    plan_path,
                    strokes_path,
                    plan_sha256,
                    state,
                    int(total_strokes),
                    current_pen,
                    int(virtual),
                    int(dry_run),
                    int(skip_cal),
                    message,
                    now,
                    now,
                ),
            )

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields or set(fields) - _ALLOWED_JOB_FIELDS:
            raise ValueError(f"허용되지 않은 job 업데이트 필드: {set(fields) - _ALLOWED_JOB_FIELDS}")
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.transaction() as conn:
            conn.execute(f"UPDATE jobs SET {cols} WHERE job_id=?", [*fields.values(), job_id])

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return dict(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (int(limit),)
            ).fetchall()
            return [dict(r) for r in rows]

    def recover_after_restart(self) -> list[str]:
        """노드 재시작 시 진행 중이던 미완료 작업을 안전하게 정리합니다."""
        active_states = ("DISPATCHING", "CALIBRATING", "DRAWING", "STOPPING")
        now = time.time()
        recovered_ids: list[str] = []
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT job_id FROM jobs WHERE state IN (?, ?, ?, ?)", active_states
            ).fetchall()
            for row in rows:
                jid = row["job_id"]
                recovered_ids.append(jid)
                conn.execute(
                    """
                    UPDATE jobs
                    SET state='RECOVERY_REQUIRED',
                        error_code='STOPPED_ON_RESTART',
                        message='프로세스 재시작으로 이전 작업이 중단되었습니다.',
                        ended_at=COALESCE(ended_at, ?),
                        updated_at=?
                    WHERE job_id=?
                    """,
                    (now, now, jid),
                )
        return recovered_ids

    # ------------------------------------------------------------------
    # 아트워크 준비(artwork_preparations) 관리
    # ------------------------------------------------------------------
    def upsert_artwork_preparation(
        self,
        *,
        job_id: str,
        stage: str,
        method: str,
        paper: str,
        detail: str,
        seed: int,
        calligraphy_text: str,
        input_path: str,
        lineart_path: str = "",
        preview_path: str = "",
        plan_path: str = "",
        approved: bool = False,
        confirmed: bool = False,
    ) -> None:
        now = time.time()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO artwork_preparations (
                    job_id, stage, method, paper, detail, seed, calligraphy_text,
                    input_path, lineart_path, preview_path, plan_path,
                    approved, confirmed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    stage=excluded.stage,
                    method=excluded.method,
                    paper=excluded.paper,
                    detail=excluded.detail,
                    seed=excluded.seed,
                    calligraphy_text=excluded.calligraphy_text,
                    input_path=excluded.input_path,
                    lineart_path=excluded.lineart_path,
                    preview_path=excluded.preview_path,
                    plan_path=excluded.plan_path,
                    approved=excluded.approved,
                    confirmed=excluded.confirmed,
                    updated_at=excluded.updated_at
                """,
                (
                    job_id,
                    stage,
                    method,
                    paper,
                    detail,
                    int(seed),
                    calligraphy_text,
                    input_path,
                    lineart_path,
                    preview_path,
                    plan_path,
                    int(approved),
                    int(confirmed),
                    now,
                    now,
                ),
            )

    # ------------------------------------------------------------------
    # 캘리브레이션 이력(calibration_runs) 관리
    # ------------------------------------------------------------------
    def save_calibration_run(
        self,
        *,
        job_id: str,
        auto_calibrate: bool,
        virtual: bool,
        slope_a: float,
        slope_b: float,
        contact_pose: list[float] | tuple[float, ...],
        safe_rect: list[float] | tuple[float, ...],
    ) -> int:
        now = time.time()
        with self.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO calibration_runs (
                    job_id, auto_calibrate, virtual, slope_a, slope_b,
                    contact_pose_json, safe_rect_json, measured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    int(auto_calibrate),
                    int(virtual),
                    float(slope_a),
                    float(slope_b),
                    json.dumps(list(contact_pose)),
                    json.dumps(list(safe_rect)),
                    now,
                ),
            )
            return int(cur.lastrowid)

    # ------------------------------------------------------------------
    # 명령 중복 방지 영수증(command_receipts) 관리
    # ------------------------------------------------------------------
    def get_command_receipt(self, job_id: str, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM command_receipts WHERE job_id=? AND request_id=?",
                (job_id, request_id),
            ).fetchone()
            return dict(row) if row else None

    def save_command_receipt(
        self,
        *,
        job_id: str,
        request_id: str,
        command: str,
        accepted: bool,
        state: str,
        error_code: str = "",
        message: str = "",
    ) -> None:
        now = time.time()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO command_receipts (
                    job_id, request_id, command, accepted, state, error_code, message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, request_id, command, int(accepted), state, error_code, message, now),
            )

    # ------------------------------------------------------------------
    # 외력 감지·중단 복귀 웨이포인트(recovery_checkpoints) 관리
    # ------------------------------------------------------------------
    def save_recovery_checkpoint(
        self,
        *,
        job_id: str,
        pen_idx: int,
        stroke_idx: int,
        point_idx: int,
        held_item_name: str,
        target_pose: list[float] | tuple[float, ...],
        actual_pose: list[float] | tuple[float, ...],
        tool_force: list[float] | tuple[float, ...] | None = None,
        contact_pose: list[float] | tuple[float, ...] | None = None,
        trigger_reason: str = "EXTERNAL_FORCE",
    ) -> int:
        now = time.time()
        with self.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO recovery_checkpoints (
                    job_id, pen_idx, stroke_idx, point_idx, held_item_name,
                    target_pose_json, actual_pose_json, tool_force_json,
                    contact_pose_json, trigger_reason, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    job_id,
                    int(pen_idx),
                    int(stroke_idx),
                    int(point_idx),
                    held_item_name,
                    json.dumps(list(target_pose)),
                    json.dumps(list(actual_pose)),
                    json.dumps(list(tool_force)) if tool_force is not None else None,
                    json.dumps(list(contact_pose)) if contact_pose is not None else None,
                    trigger_reason,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def get_pending_checkpoint(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT * FROM recovery_checkpoints
                WHERE job_id=? AND status='PENDING'
                ORDER BY created_at DESC LIMIT 1
                """,
                (job_id,),
            ).fetchone()
            if not row:
                return None
            data = dict(row)
            data["target_pose"] = json.loads(data["target_pose_json"])
            data["actual_pose"] = json.loads(data["actual_pose_json"])
            data["tool_force"] = json.loads(data["tool_force_json"]) if data["tool_force_json"] else None
            data["contact_pose"] = json.loads(data["contact_pose_json"]) if data["contact_pose_json"] else None
            return data

    def mark_checkpoint_status(self, checkpoint_id: int, status: str) -> None:
        if status not in ("RECOVERED", "ABORTED"):
            raise ValueError(f"잘못된 복구 상태: {status}")
        now = time.time()
        with self.transaction() as conn:
            conn.execute(
                "UPDATE recovery_checkpoints SET status=?, recovered_at=? WHERE id=?",
                (status, now, int(checkpoint_id)),
            )

    # ------------------------------------------------------------------
    # 주요 이벤트 로그(job_events) 관리
    # ------------------------------------------------------------------
    def append_event(
        self,
        *,
        job_id: str,
        event_type: str,
        state: str,
        current_pen: str = "",
        completed_strokes: int = 0,
        total_strokes: int = 0,
        resume_stroke_id: int = 0,
        seq: int = 0,
        command: str = "",
        request_id: str = "",
        error_code: str = "",
        detail: str = "",
        occurred_at: float | None = None,
    ) -> None:
        now = time.time()
        event_time = float(occurred_at) if occurred_at is not None else now
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO job_events (
                    seq, event_type, job_id, state, completed_strokes, total_strokes,
                    resume_stroke_id, current_pen, command, request_id, error_code,
                    detail, occurred_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(seq),
                    event_type,
                    job_id,
                    state,
                    int(completed_strokes),
                    int(total_strokes),
                    int(resume_stroke_id),
                    current_pen,
                    command,
                    request_id,
                    error_code,
                    detail,
                    event_time,
                    now,
                ),
            )

    # ------------------------------------------------------------------
    # JobManager -> SQLite 단방향 신호(JobDecision) 처리 (SQLITE_SIGNAL_CONTRACT_KR.md)
    # ------------------------------------------------------------------
    def apply_job_decision(self, decision: Any) -> None:
        """art_interfaces/msg/JobDecision 또는 JobDecision 이벤트를 SQLite에 반영합니다."""
        seq = int(getattr(decision, "seq", 0) or 0)
        event_type = str(getattr(decision, "event_type", "") or "")
        job_id = str(getattr(decision, "job_id", "") or "")
        state = str(getattr(decision, "state", "") or "")
        completed_strokes = int(getattr(decision, "completed_strokes", 0) or 0)
        total_strokes = int(getattr(decision, "total_strokes", 0) or 0)
        resume_stroke_id = int(getattr(decision, "resume_stroke_id", 0) or 0)
        current_pen = str(getattr(decision, "current_pen", "") or "")
        plan_path = str(getattr(decision, "plan_path", "") or "")
        plan_sha256 = str(getattr(decision, "plan_sha256", "") or "")
        command = str(getattr(decision, "command", "") or "")
        request_id = str(getattr(decision, "request_id", "") or "")
        error_code = str(getattr(decision, "error_code", "") or "")
        message = str(getattr(decision, "message", "") or "")
        raw_occurred = float(getattr(decision, "occurred_at", 0.0) or 0.0)
        now = time.time()
        occurred_at = raw_occurred if raw_occurred > 0.0 else now

        with self.transaction() as conn:
            # 1) 모든 JobDecision을 시간순(occurred_at, seq)으로 감사 로그에 누적
            conn.execute(
                """
                INSERT INTO job_events (
                    seq, event_type, job_id, state, completed_strokes, total_strokes,
                    resume_stroke_id, current_pen, command, request_id, error_code,
                    detail, occurred_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seq,
                    event_type,
                    job_id,
                    state,
                    completed_strokes,
                    total_strokes,
                    resume_stroke_id,
                    current_pen,
                    command,
                    request_id,
                    error_code,
                    message,
                    occurred_at,
                    now,
                ),
            )

            # JOB_REJECTED는 실제 작업이 생성되지 않았으므로 job_events에만 남김
            if not job_id or event_type == "JOB_REJECTED":
                return

            # 2) jobs 테이블은 job_id 기준으로 Upsert 처리
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, plan_path, plan_sha256, state,
                    completed_strokes, total_strokes, resume_stroke_id, current_pen,
                    error_code, message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    plan_path=CASE WHEN excluded.plan_path != '' THEN excluded.plan_path ELSE jobs.plan_path END,
                    plan_sha256=CASE WHEN excluded.plan_sha256 != '' THEN excluded.plan_sha256 ELSE jobs.plan_sha256 END,
                    state=CASE WHEN excluded.state != '' THEN excluded.state ELSE jobs.state END,
                    completed_strokes=MAX(jobs.completed_strokes, excluded.completed_strokes),
                    total_strokes=CASE WHEN excluded.total_strokes > 0 THEN excluded.total_strokes ELSE jobs.total_strokes END,
                    resume_stroke_id=CASE
                        WHEN excluded.event_type_marker = 'RECOVERY_COMPLETED' THEN 0
                        WHEN excluded.resume_stroke_id > 0 THEN excluded.resume_stroke_id
                        ELSE jobs.resume_stroke_id
                    END,
                    current_pen=CASE WHEN excluded.current_pen != '' THEN excluded.current_pen ELSE jobs.current_pen END,
                    error_code=excluded.error_code,
                    message=CASE WHEN excluded.message != '' THEN excluded.message ELSE jobs.message END,
                    updated_at=excluded.updated_at
                """.replace(
                    "WHEN excluded.event_type_marker = 'RECOVERY_COMPLETED'",
                    "WHEN ? = 'RECOVERY_COMPLETED'",
                ),
                (
                    job_id,
                    plan_path,
                    plan_sha256,
                    state or "QUEUED",
                    completed_strokes,
                    total_strokes,
                    resume_stroke_id,
                    current_pen,
                    error_code,
                    message,
                    occurred_at,
                    occurred_at,
                    event_type,
                ),
            )

            if event_type == "JOB_DISPATCHED":
                conn.execute(
                    "UPDATE jobs SET started_at=COALESCE(started_at, ?) WHERE job_id=?",
                    (occurred_at, job_id),
                )
            elif event_type == "JOB_FINISHED":
                conn.execute(
                    "UPDATE jobs SET ended_at=? WHERE job_id=?",
                    (occurred_at, job_id),
                )

            # 3) 제어 명령 기록(command_receipts): CONTROL_REQUESTED / CONTROL_APPLIED / RECOVERY_STARTED
            if event_type in ("CONTROL_REQUESTED", "CONTROL_APPLIED", "RECOVERY_STARTED") and request_id:
                accepted = 0 if error_code else 1
                conn.execute(
                    """
                    INSERT INTO command_receipts (
                        job_id, request_id, command, accepted, state, error_code, message, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id, request_id) DO UPDATE SET
                        accepted=excluded.accepted,
                        state=excluded.state,
                        error_code=excluded.error_code,
                        message=excluded.message
                    """,
                    (job_id, request_id, command, accepted, state, error_code, message, occurred_at),
                )


class SqliteDecisionSink:
    """art_job_manager의 DecisionSink Protocol을 구현한 단방향 SQLite 어댑터."""

    def __init__(self, store: RobotStateStore) -> None:
        self.store = store

    def emit(self, decision: Any) -> None:
        self.store.apply_job_decision(decision)
