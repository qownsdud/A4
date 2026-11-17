# [파일 역할] 구형 시뮬레이션 상태 머신
# [동작] 내장 가상 진행률을 이용하는 JobManagerTestNode에서 사용합니다.
# [주의] 운영용 JobManager는 이 코드가 아니라 production_engine.py를 사용합니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""ROS-free JobManager state machine: durable commands + safe stroke checkpoint.

Default mode is controller-disconnected: a new job stays QUEUED. `simulation=True`
is an explicit TEST-ONLY simulation; no Doosan/RG2 driver is called.

TEAM_SYNC(Controller): connect the on_controller_* methods to a verified robot
Action/feedback adapter. Do not infer PAUSED or stroke completion from HTTP 202.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .job_repository import JobRepository
from .plan import PlanError, load_plan

ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
ACTIVE = {'QUEUED', 'DRAWING', 'PAUSING', 'PAUSED', 'STOPPING', 'RECOVERY_REQUIRED'}
SIM_ONLY_MESSAGE = 'SIMULATION ONLY: no robot control'


@dataclass(frozen=True)
class Reply:
    accepted: bool
    job_id: str
    state: str
    error_code: str = ''
    message: str = ''


# [핵심 기능] 구형 시뮬레이션 모드의 작업 상태 머신
class JobEngine:
    def __init__(self, db_path: str | Path, *, plan_root: str | Path, simulation: bool = False):
        self.repo = JobRepository(db_path)
        self.plan_root = Path(plan_root).expanduser()
        self.simulation = simulation
        self._simulation_pens: dict[str, tuple[str, ...]] = {}
        self.recovered_jobs = self.repo.recover_after_restart()

    # [핵심 기능] SQLite 연결 종료
    def close(self):
        self.repo.close()

    # [핵심 기능] 단일 작업 상태를 DB에서 반환
    def status(self, job_id: str) -> dict | None:
        return self.repo.get(job_id)

    # [핵심 기능] 전체 작업 상태 목록 반환
    def statuses(self) -> list[dict]:
        return self.repo.all_jobs()

    # [핵심 기능] 신규 작업 등록 Service 요청 전송
    def create_job(self, job_id: str, plan_path: str) -> Reply:
        if not ID.fullmatch(job_id):
            return Reply(False, job_id, 'REJECTED', 'INVALID_JOB_ID')
        with self.repo.transaction() as conn:
            row = conn.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if row:
                return Reply(False, job_id, row['state'], 'DUPLICATE_JOB')
            other = conn.execute("SELECT job_id FROM jobs WHERE state IN ('QUEUED','DRAWING','PAUSING','PAUSED','STOPPING','RECOVERY_REQUIRED') LIMIT 1").fetchone()
            if other:
                return Reply(False, job_id, 'REJECTED', 'SYSTEM_BUSY', f'Active job: {other[0]}')
            try:
                plan = load_plan(job_id, plan_path, plan_root=self.plan_root)
            except PlanError as exc:
                return Reply(False, job_id, 'REJECTED', str(exc))
            state = 'DRAWING' if self.simulation else 'QUEUED'
            message = SIM_ONLY_MESSAGE if self.simulation else 'Awaiting real controller integration; no motion started'
            self.repo.insert(conn, job_id=job_id, plan_path=plan.path, plan_sha256=plan.sha256,
                             state=state, total_strokes=plan.stroke_count, current_pen=plan.pen_ids[0], message=message)
            if self.simulation:
                self._simulation_pens[job_id] = plan.pen_ids
            return Reply(True, job_id, state, message=message)

    # [핵심 기능] PAUSE/RESUME/CANCEL Service 요청 전송
    def control_job(self, job_id: str, command: str, request_id: str) -> Reply:
        if not ID.fullmatch(job_id) or not ID.fullmatch(request_id):
            return Reply(False, job_id, 'UNKNOWN', 'INVALID_ID')
        with self.repo.transaction() as conn:
            previous = conn.execute('''SELECT * FROM command_receipts
                WHERE job_id=? AND request_id=?''', (job_id, request_id)).fetchone()
            if previous:
                if previous['command'] != command:
                    return Reply(False, job_id, previous['state'], 'REQUEST_ID_CONFLICT', 'Same request_id used for different command')
                # The original accept/reject decision is durable, but the state
                # in the replay must reflect the CURRENT job, not stale PAUSING.
                current = conn.execute('SELECT state FROM jobs WHERE job_id=?', (job_id,)).fetchone()
                current_state = current['state'] if current else previous['state']
                return Reply(bool(previous['accepted']), job_id, current_state,
                             previous['error_code'], previous['message'] + ' [request_id replay]')
            job = conn.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not job:
                return Reply(False, job_id, 'UNKNOWN', 'JOB_NOT_FOUND')
            state = job['state']
            reply = None
            if command not in ('PAUSE', 'RESUME', 'CANCEL'):
                reply = Reply(False, job_id, state, 'UNKNOWN_COMMAND')
            elif command == 'PAUSE' and state == 'DRAWING':
                self.repo.patch(conn, job_id, state='PAUSING', message=SIM_ONLY_MESSAGE if self.simulation else 'Waiting for controller stop acknowledgment')
                reply = Reply(True, job_id, 'PAUSING', message='Pause request queued; not yet PAUSED')
            elif command == 'RESUME' and state == 'PAUSED':
                if job['uncertain_stroke'] is not None:
                    reply = Reply(False, job_id, state, 'UNCERTAIN_STROKE', 'Operator review required before resuming')
                else:
                    try:
                        current_plan = load_plan(job_id, job['plan_path'], plan_root=self.plan_root)
                    except PlanError:
                        current_plan = None
                    if current_plan is None or current_plan.sha256 != job['plan_sha256']:
                        reply = Reply(False, job_id, state, 'PLAN_CHANGED', 'DrawingPlan changed or inaccessible')
                    elif not self.simulation:
                        # This package has no controller adapter. No pretending to resume motion.
                        reply = Reply(False, job_id, state, 'CONTROLLER_NOT_CONNECTED')
                    else:
                        self.repo.patch(conn, job_id, state='DRAWING', message=SIM_ONLY_MESSAGE)
                        reply = Reply(True, job_id, 'DRAWING', message=SIM_ONLY_MESSAGE)
            elif command == 'CANCEL' and state == 'QUEUED':
                self.repo.patch(conn, job_id, state='STOPPED', message='Cancelled before controller start')
                reply = Reply(True, job_id, 'STOPPED', message='No motion had started')
            elif command == 'CANCEL' and state in ('DRAWING', 'PAUSING', 'PAUSED'):
                self.repo.patch(conn, job_id, state='STOPPING', message='Waiting for controller stop acknowledgment')
                reply = Reply(True, job_id, 'STOPPING', message='Cancel requested; not confirmed STOPPED')
            else:
                reply = Reply(False, job_id, state, 'INVALID_TRANSITION')
            conn.execute('''INSERT INTO command_receipts
                (job_id, request_id, command, accepted, state, error_code, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))''',
                (job_id, request_id, command, int(reply.accepted), reply.state, reply.error_code, reply.message))
            return reply

    # The following APIs have NO public ROS services in this initial release.
    # TEAM_SYNC(Controller): call ONLY on authenticated/trusted Action feedback,
    # never from kiosk/UI user input.
    # [핵심 기능] Controller가 실제 실행을 시작했음을 기록
    def on_controller_started(self, job_id: str) -> bool:
        with self.repo.transaction() as conn:
            row = conn.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not row or row['state'] != 'QUEUED':
                return False
            self.repo.patch(conn, job_id, state='DRAWING', message='Controller started (trusted feedback)')
            return True

    # [핵심 기능] 시뮬레이션/검증된 외부 확인으로 PAUSED 처리
    def on_controller_paused(self, job_id: str) -> bool:
        with self.repo.transaction() as conn:
            row = conn.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not row or row['state'] != 'PAUSING':
                return False
            self.repo.patch(conn, job_id, state='PAUSED', message='Controller confirmed motion stopped and pen safe')
            return True

    # [핵심 기능] 시뮬레이션/검증된 외부 확인으로 STOPPED 처리
    def on_controller_stopped(self, job_id: str) -> bool:
        with self.repo.transaction() as conn:
            row = conn.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not row or row['state'] != 'STOPPING':
                return False
            self.repo.patch(conn, job_id, state='STOPPED', message='Controller confirmed motion stopped')
            return True

    # [핵심 기능] 새 획을 진행 중(UNCERTAIN 가능)으로 저장
    def on_stroke_started(self, job_id: str, stroke_id: int, pen: str) -> bool:
        with self.repo.transaction() as conn:
            row = conn.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if (not row or row['state'] != 'DRAWING' or row['uncertain_stroke'] is not None
                    or type(stroke_id) is not int or stroke_id != row['completed_strokes'] + 1
                    or stroke_id > row['total_strokes'] or not pen):
                return False
            self.repo.patch(conn, job_id, uncertain_stroke=stroke_id, current_pen=pen,
                            message=f'Stroke {stroke_id} in progress; not committed')
            return True

    # [핵심 기능] 모의·시험 작업에서 펜 이격 후 획을 확정
    def on_stroke_finished(self, job_id: str, stroke_id: int, *, pen_lift_confirmed: bool) -> bool:
        if not pen_lift_confirmed:
            return False
        with self.repo.transaction() as conn:
            row = conn.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if (not row or row['state'] != 'DRAWING' or row['uncertain_stroke'] != stroke_id
                    or stroke_id != row['completed_strokes'] + 1):
                return False
            new_state = 'COMPLETED' if stroke_id == row['total_strokes'] else 'DRAWING'
            self.repo.patch(conn, job_id, completed_strokes=stroke_id, uncertain_stroke=None,
                            state=new_state, message='Stroke committed after pen lift' if new_state != 'COMPLETED' else 'Drawing completed')
            return True

    # [핵심 기능] 내장 테스트 시뮬레이션의 가상 진행률만 갱신
    def simulate_tick(self):
        """TEST ONLY: emulate a full stroke + confirmed pen lift per timer tick."""
        if not self.simulation:
            return
        for job in self.statuses():
            job_id, state = job['job_id'], job['state']
            if state == 'DRAWING':
                if job['uncertain_stroke'] is not None:
                    # Never silently mark an interrupted stroke done.
                    with self.repo.transaction() as conn:
                        self.repo.patch(conn, job_id, state='RECOVERY_REQUIRED',
                                        error_code='UNCERTAIN_STROKE', message='Manual review required')
                else:
                    stroke_id = job['completed_strokes'] + 1
                    # No hardware; do not claim real stroke completion.
                    pen_ids = self._simulation_pens.get(job_id)
                    if pen_ids is None:
                        # A restarted in-flight simulation was marked RECOVERY_REQUIRED
                        # and must not be resumed automatically.
                        continue
                    if self.on_stroke_started(job_id, stroke_id, pen_ids[stroke_id - 1]):
                        self.on_stroke_finished(job_id, stroke_id, pen_lift_confirmed=True)
            elif state == 'PAUSING':
                self.on_controller_paused(job_id)  # simulated stop/pen-safe ack
            elif state == 'STOPPING':
                self.on_controller_stopped(job_id)  # simulated stop ack
