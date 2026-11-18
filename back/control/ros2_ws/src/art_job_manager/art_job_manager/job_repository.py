# [파일 역할] SQLite 영속 저장소
# [동작] jobs 테이블과 command_receipts 테이블을 관리하고 재시작 후 안전 상태를 복구합니다.
# [주의] 중복 request_id 기록 및 uncertain_stroke 체크포인트가 핵심입니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""SQLite repository: durable job state, per-stroke checkpoint and command idempotency.

TEAM_SYNC(Controller): completed_strokes can advance ONLY after a controller
confirms both stroke completion AND pen lift. No ROS or robot imports here.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


# [핵심 기능] 작업 상태·중복 제어 요청을 SQLite에 저장하는 저장소
class JobRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA busy_timeout=10000')
        self.conn.execute('PRAGMA synchronous=FULL')
        with self.transaction() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                plan_path TEXT NOT NULL,
                plan_sha256 TEXT NOT NULL,
                state TEXT NOT NULL,
                completed_strokes INTEGER NOT NULL DEFAULT 0,
                total_strokes INTEGER NOT NULL,
                uncertain_stroke INTEGER,
                current_pen TEXT NOT NULL DEFAULT '',
                error_code TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )''')
            # 기존 DB를 삭제하지 않고 동일 실행 유지 여부만 추가합니다.
            columns = {r[1] for r in conn.execute('PRAGMA table_info(jobs)')}
            if 'live_execution' not in columns:
                conn.execute('ALTER TABLE jobs ADD COLUMN live_execution INTEGER NOT NULL DEFAULT 0')
            conn.execute('''CREATE TABLE IF NOT EXISTS command_receipts (
                job_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                command TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                state TEXT NOT NULL,
                error_code TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY(job_id, request_id)
            )''')

    @contextmanager
    def transaction(self):
        with self._lock:
            try:
                self.conn.execute('BEGIN IMMEDIATE')
                yield self.conn
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    # [핵심 기능] 단일 작업 상태 조회
    def get(self, job_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            return dict(row) if row else None

    # [핵심 기능] 저장된 전체 작업 조회
    def all_jobs(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute('SELECT * FROM jobs ORDER BY created_at')]

    @staticmethod
    # [핵심 기능] 신규 작업의 초기 DB 상태 저장
    def insert(conn, *, job_id: str, plan_path: str, plan_sha256: str, state: str, total_strokes: int, current_pen: str, message: str):
        now = time.time()
        conn.execute('''INSERT INTO jobs (job_id, plan_path, plan_sha256, state, total_strokes,
                        current_pen, message, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                     (job_id, plan_path, plan_sha256, state, total_strokes, current_pen, message, now, now))

    @staticmethod
    # [핵심 기능] 기존 작업 상태·완료 획·오류 기록 등을 DB에 갱신
    def patch(conn, job_id: str, **fields):
        valid = {'state', 'completed_strokes', 'uncertain_stroke', 'current_pen', 'error_code', 'message', 'live_execution'}
        if not fields or set(fields) - valid:
            raise ValueError('Invalid job state update fields')
        fields['updated_at'] = time.time()
        cols = ', '.join(f'{key}=?' for key in fields)
        conn.execute(f'UPDATE jobs SET {cols} WHERE job_id=?', [*fields.values(), job_id])

    # [핵심 기능] 재시작 직전 진행 중이던 작업을 STOPPED로 정리해 바로 새 작업을 받을 수 있게 함
    def recover_after_restart(self) -> list[str]:
        with self.transaction() as conn:
            rows = conn.execute('''SELECT job_id FROM jobs WHERE state IN
                ('DRAWING','PAUSING','PAUSED','RESUMING','STOPPING','RECOVERY_REQUIRED')''').fetchall()
            for row in rows:
                self.patch(conn, row['job_id'], state='STOPPED',
                           error_code='STOPPED_ON_RESTART',
                           message='재시작으로 이전 작업을 종료했습니다.')
            return []

    # [핵심 기능] SQLite 연결 종료
    def close(self):
        with self._lock:
            self.conn.close()
