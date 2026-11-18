# [파일 역할] 중단 획 복구 테스트용 가짜 저장소
# [동작] 안전 체크포인트/복구 정책을 단순화해 검증하는 테스트 지원 파일입니다.
# [주의] 실제 SQLite 저장소나 로봇 상태를 대신하지 않습니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""SQLite mock checkpoint repository; NOT the real JobManager repository.

TEAM_SYNC(JobManager/Robot): confirm the schema, pen-up verification source,
transaction timing, uncertain-stroke and recovery semantics before integration.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class CheckpointStub:
    def __init__(self, db_file: str | Path):
        self.conn = sqlite3.connect(str(db_file))
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                job_id TEXT PRIMARY KEY,
                last_completed_stroke INTEGER NOT NULL DEFAULT 0,
                uncertain_stroke INTEGER,
                current_pen TEXT NOT NULL DEFAULT '',
                error_code TEXT NOT NULL DEFAULT ''
            )
        """)
        self.conn.commit()

    def begin_stroke(self, job_id: str, stroke_id: int, pen: str) -> None:
        if stroke_id <= 0:
            raise ValueError("stroke_id must be >= 1")
        with self.conn:
            self.conn.execute("""
                INSERT INTO checkpoints(job_id, uncertain_stroke, current_pen)
                VALUES (?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    uncertain_stroke=excluded.uncertain_stroke,
                    current_pen=excluded.current_pen
            """, (job_id, stroke_id, pen))

    def complete_stroke(self, job_id: str, stroke_id: int, *, pen_lift_confirmed: bool) -> bool:
        if not pen_lift_confirmed:
            return False
        with self.conn:
            cur = self.conn.execute("""
                UPDATE checkpoints SET last_completed_stroke=?, uncertain_stroke=NULL
                WHERE job_id=? AND uncertain_stroke=? AND last_completed_stroke < ?
            """, (stroke_id, job_id, stroke_id, stroke_id))
            return cur.rowcount == 1

    # [핵심 기능] 단일 작업 상태 조회
    def get(self, job_id: str) -> tuple[int, int | None, str] | None:
        row = self.conn.execute("""
            SELECT last_completed_stroke, uncertain_stroke, current_pen
            FROM checkpoints WHERE job_id=?
        """, (job_id,)).fetchone()
        return row

    # [핵심 기능] SQLite 연결 종료
    def close(self) -> None:
        self.conn.close()
