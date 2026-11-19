-- A4 드로잉 시스템 SQLite 스키마 (SQLITE_SIGNAL_CONTRACT_KR.md 규격 준수)
-- 권장 PRAGMA: journal_mode=WAL, busy_timeout=10000, synchronous=FULL, foreign_keys=ON

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    plan_path TEXT NOT NULL DEFAULT '',
    strokes_path TEXT NOT NULL DEFAULT '',
    plan_sha256 TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,                 -- REJECTED | QUEUED | DISPATCHING | DRAWING | PAUSING | PAUSED | RESUMING | STOPPING | STOPPED | COMPLETED | RECOVERY_REQUIRED
    completed_strokes INTEGER NOT NULL DEFAULT 0,
    total_strokes INTEGER NOT NULL DEFAULT 0,
    resume_stroke_id INTEGER NOT NULL DEFAULT 0, -- 외력 정지·복구 시 재개 기준 획 번호
    current_pen TEXT NOT NULL DEFAULT '',
    virtual INTEGER NOT NULL DEFAULT 0,
    dry_run INTEGER NOT NULL DEFAULT 0,
    skip_cal INTEGER NOT NULL DEFAULT 0,
    exit_code INTEGER,
    error_code TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    started_at REAL,
    ended_at REAL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS artwork_preparations (
    job_id TEXT PRIMARY KEY,
    stage TEXT NOT NULL,                 -- LINEART | PLAN | PREPARED
    method TEXT NOT NULL,                -- cv | dl | mfl_ld
    paper TEXT NOT NULL,                 -- a4 | a4_landscape_margin | postcard | square
    detail TEXT NOT NULL,                -- high | medium | low
    seed INTEGER NOT NULL DEFAULT 42,
    calligraphy_text TEXT NOT NULL DEFAULT '',
    input_path TEXT NOT NULL,
    lineart_path TEXT NOT NULL DEFAULT '',
    preview_path TEXT NOT NULL DEFAULT '',
    plan_path TEXT NOT NULL DEFAULT '',
    approved INTEGER NOT NULL DEFAULT 0,
    confirmed INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS calibration_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    auto_calibrate INTEGER NOT NULL DEFAULT 0,
    virtual INTEGER NOT NULL DEFAULT 0,
    slope_a REAL NOT NULL DEFAULT 0.0,
    slope_b REAL NOT NULL DEFAULT 0.0,
    contact_pose_json TEXT NOT NULL,     -- [x, y, z, rx, ry, rz]
    safe_rect_json TEXT NOT NULL,        -- [xmin, xmax, ymin, ymax]
    measured_at REAL NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS command_receipts (
    job_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    command TEXT NOT NULL,               -- PAUSE | RESUME | CANCEL | RECOVER
    accepted INTEGER NOT NULL,
    state TEXT NOT NULL,
    error_code TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    PRIMARY KEY (job_id, request_id)
);

CREATE TABLE IF NOT EXISTS recovery_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    pen_idx INTEGER NOT NULL,
    stroke_idx INTEGER NOT NULL,
    point_idx INTEGER NOT NULL,
    held_item_name TEXT NOT NULL DEFAULT '',
    target_pose_json TEXT NOT NULL,      -- 복귀해야 할 직전 정상 목표 좌표 [x, y, z, rx, ry, rz]
    actual_pose_json TEXT NOT NULL,      -- 외력 감지 직후 밀린 실제 좌표 [x, y, z, rx, ry, rz]
    tool_force_json TEXT,                -- 감지 당시 외력 [fx, fy, fz, tx, ty, tz]
    contact_pose_json TEXT,              -- 당시 적용된 기준 바닥 접촉 좌표
    trigger_reason TEXT NOT NULL,        -- EXTERNAL_FORCE | USER_CANCEL | ROBOT_ERROR
    status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING | RECOVERED | ABORTED
    created_at REAL NOT NULL,
    recovered_at REAL,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recovery_pending
    ON recovery_checkpoints(job_id, status, created_at DESC);

-- 수신한 모든 JobDecision(JOB_REJECTED 포함)을 시간순(occurred_at, seq)으로 누적 저장
CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seq INTEGER NOT NULL DEFAULT 0,
    event_type TEXT NOT NULL,
    job_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    completed_strokes INTEGER NOT NULL DEFAULT 0,
    total_strokes INTEGER NOT NULL DEFAULT 0,
    resume_stroke_id INTEGER NOT NULL DEFAULT 0,
    current_pen TEXT NOT NULL DEFAULT '',
    command TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    occurred_at REAL NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_events_seq
    ON job_events(occurred_at, seq);

CREATE INDEX IF NOT EXISTS idx_job_events_job_time
    ON job_events(job_id, occurred_at DESC);
