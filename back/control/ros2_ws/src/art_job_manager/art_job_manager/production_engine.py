# [파일 역할] 실제 JobManager 작업 규칙/상태 머신
# [동작] 작업 생성, PAUSE/RESUME/CANCEL, Action 피드백 검증, 획 체크포인트·복구 판정을 담당합니다.
# [주의] STROKE_COMPLETED + pen_up_confirmed가 확인돼야 완료 획으로 저장합니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Fail-closed, ROS-independent production JobManager state machine.

No simulated progress and no direct Doosan motion commands exist here. Only
validated feedback/results from the configured DrawingController Action may
advance confirmed stroke checkpoints.

TEAM_SYNC(Controller): action feedback semantics must match ExecuteDrawing.action.
TEAM_SYNC(Backend/Pipeline): one immutable, job-specific DrawingPlan per job_id.
TEAM_SYNC(UI): PAUSING/STOPPING are *requests*, not safety confirmations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .job_repository import JobRepository
from .plan import PlanError, load_plan

_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
_BLOCKING = ('QUEUED', 'DISPATCHING', 'DRAWING', 'PAUSING', 'PAUSED', 'RESUMING', 'STOPPING')


@dataclass(frozen=True)
class Reply:
    accepted: bool
    job_id: str
    state: str
    error_code: str = ''
    message: str = ''


@dataclass(frozen=True)
class Dispatch:
    job_id: str
    plan_path: str
    plan_sha256: str
    start_stroke_id: int


# [핵심 기능] 실제 Controller 피드백을 신뢰 가능한 조건에서만 반영하는 작업 상태 머신
class ProductionEngine:
    def __init__(self, db_path: str | Path, *, plan_root: str | Path):
        self.repo = JobRepository(db_path)
        self.plan_root = Path(plan_root).expanduser()
        self._pens: dict[str, tuple[str, ...]] = {}
        # 재시작 시 이전 미완료/복구 필요 작업은 모두 STOPPED로 정리해 바로 새 작업을 시작할 수 있게 합니다.
        cleanup_states = _BLOCKING + ('RECOVERY_REQUIRED',)
        with self.repo.transaction() as con:
            rows = con.execute('SELECT job_id FROM jobs WHERE state IN (' +
                               ','.join('?' for _ in cleanup_states) + ')', cleanup_states).fetchall()
            for row in rows:
                self.repo.patch(con, row['job_id'], state='STOPPED',
                                error_code='STOPPED_ON_RESTART',
                                message='재시작으로 이전 작업을 종료했습니다.')
        self.recovered_jobs = []

    # [핵심 기능] SQLite 연결 종료
    def close(self) -> None:
        self.repo.close()

    # [핵심 기능] 단일 작업 상태를 DB에서 반환
    def status(self, job_id: str):
        return self.repo.get(job_id)

    # [핵심 기능] 전체 작업 상태 목록 반환
    def statuses(self):
        return self.repo.all_jobs()

    # [핵심 기능] 신규 작업 등록 Service 요청 전송
    def create_job(self, job_id: str, plan_path: str) -> Reply:
        if not _ID.fullmatch(job_id):
            return Reply(False, job_id, 'REJECTED', 'INVALID_JOB_ID')
        with self.repo.transaction() as con:
            exists = con.execute('SELECT state FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if exists:
                return Reply(False, job_id, exists['state'], 'DUPLICATE_JOB')
            busy = con.execute('SELECT job_id FROM jobs WHERE state IN (' +
                               ','.join('?' for _ in _BLOCKING) + ') LIMIT 1', _BLOCKING).fetchone()
            if busy:
                return Reply(False, job_id, 'REJECTED', 'SYSTEM_BUSY', 'Active job: ' + busy['job_id'])
            try:
                plan = load_plan(job_id, plan_path, plan_root=self.plan_root)
            except PlanError as exc:
                return Reply(False, job_id, 'REJECTED', str(exc))
            self.repo.insert(con, job_id=job_id, plan_path=plan.path, plan_sha256=plan.sha256,
                             state='QUEUED', total_strokes=plan.stroke_count,
                             current_pen=plan.pen_ids[0],
                             message='Queued; waiting for /art/execute_drawing action server')
            self._pens[job_id] = plan.pen_ids
            return Reply(True, job_id, 'QUEUED')

    # [핵심 기능] QUEUED 상태의 작업을 실제 Controller Goal로 보낼 수 있는지 검증
    def prepare_dispatch(self, job_id: str) -> Dispatch | None:
        with self.repo.transaction() as con:
            job = con.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not job or job['state'] != 'QUEUED':
                return None
            try:
                plan = load_plan(job_id, job['plan_path'], plan_root=self.plan_root)
            except PlanError as exc:
                self.repo.patch(con, job_id, state='STOPPED', error_code='PLAN_UNAVAILABLE',
                                message='Plan inaccessible: ' + str(exc))
                return None
            if plan.sha256 != job['plan_sha256'] or plan.stroke_count != job['total_strokes']:
                self.repo.patch(con, job_id, state='STOPPED', error_code='PLAN_CHANGED',
                                message='Immutable DrawingPlan changed; cannot dispatch')
                return None
            start = job['completed_strokes'] + 1
            if start > job['total_strokes'] or job['uncertain_stroke'] is not None:
                self.repo.patch(con, job_id, state='STOPPED', error_code='UNCERTAIN_STROKE',
                                message='Unconfirmed stroke; job stopped')
                return None
            self._pens[job_id] = plan.pen_ids
            self.repo.patch(con, job_id, state='DISPATCHING', error_code='',
                            message='Goal being sent; no motion confirmed')
            return Dispatch(job_id, job['plan_path'], job['plan_sha256'], start)

    # [핵심 기능] PAUSE/RESUME/CANCEL Service 요청 전송
    def control_job(self, job_id: str, command: str, request_id: str) -> Reply:
        if not _ID.fullmatch(job_id) or not _ID.fullmatch(request_id):
            return Reply(False, job_id, 'UNKNOWN', 'INVALID_ID')
        with self.repo.transaction() as con:
            prev = con.execute('SELECT * FROM command_receipts WHERE job_id=? AND request_id=?',
                               (job_id, request_id)).fetchone()
            if prev:
                if command != prev['command']:
                    return Reply(False, job_id, prev['state'], 'REQUEST_ID_CONFLICT')
                now = con.execute('SELECT state FROM jobs WHERE job_id=?', (job_id,)).fetchone()
                return Reply(bool(prev['accepted']), job_id, now['state'] if now else prev['state'],
                             prev['error_code'], prev['message'] + ' [request_id replay]')
            job = con.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not job:
                return Reply(False, job_id, 'UNKNOWN', 'JOB_NOT_FOUND')
            state = job['state']
            if command == 'CANCEL' and state == 'QUEUED':
                self.repo.patch(con, job_id, state='STOPPED', message='Cancelled before action dispatch')
                reply = Reply(True, job_id, 'STOPPED')
            elif command == 'CANCEL' and state == 'PAUSED' and not job['live_execution']:
                self.repo.patch(con, job_id, state='STOPPED', message='Cancelled while controller confirmed safely paused')
                reply = Reply(True, job_id, 'STOPPED')
            elif command == 'PAUSE' and state in ('DISPATCHING', 'DRAWING'):
                self.repo.patch(con, job_id, state='PAUSING', message='Pause pending controller confirmation')
                reply = Reply(True, job_id, 'PAUSING')
            elif command == 'CANCEL' and (state in ('DISPATCHING', 'DRAWING', 'PAUSING', 'RESUMING')
                                         or state == 'PAUSED' and job['live_execution']):
                self.repo.patch(con, job_id, state='STOPPING', message='Cancel pending controller confirmation')
                reply = Reply(True, job_id, 'STOPPING')
            elif command == 'RESUME' and state == 'PAUSED':
                if job['uncertain_stroke'] is not None and not job['live_execution']:
                    reply = Reply(False, job_id, state, 'UNCERTAIN_STROKE',
                                  'Interrupted stroke cannot be replayed automatically')
                else:
                    try:
                        plan = load_plan(job_id, job['plan_path'], plan_root=self.plan_root)
                    except PlanError:
                        plan = None
                    if plan is None or plan.sha256 != job['plan_sha256']:
                        reply = Reply(False, job_id, state, 'PLAN_CHANGED')
                    else:
                        target = 'RESUMING' if job['live_execution'] else 'QUEUED'
                        self.repo.patch(con, job_id, state=target, message=(
                            '동일 모션 재개 확인 중' if job['live_execution'] else 'Resume queued for new action goal'))
                        reply = Reply(True, job_id, target)
            else:
                reply = Reply(False, job_id, state,
                              'UNKNOWN_COMMAND' if command not in ('PAUSE', 'RESUME', 'CANCEL') else 'INVALID_TRANSITION')
            con.execute('''INSERT INTO command_receipts
                (job_id,request_id,command,accepted,state,error_code,message,created_at)
                VALUES (?,?,?,?,?,?,?,strftime('%s','now'))''',
                (job_id, request_id, command, int(reply.accepted), reply.state,
                 reply.error_code, reply.message))
            return reply

    # [핵심 기능] Controller가 실제 실행을 시작했음을 기록
    def on_controller_started(self, job_id: str, *, live_execution=False) -> bool:
        with self.repo.transaction() as con:
            row = con.execute('SELECT state FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not row or row['state'] not in ('DISPATCHING', 'DRAWING', 'PAUSING', 'STOPPING'):
                return False
            if live_execution:
                self.repo.patch(con, job_id, live_execution=1)
            if row['state'] == 'DISPATCHING':
                self.repo.patch(con, job_id, state='DRAWING', message='Controller confirmed action execution')
            return True

    # [핵심 기능] 새 획을 진행 중(UNCERTAIN 가능)으로 저장
    def on_stroke_started(self, job_id: str, stroke_id: int, pen_id: str) -> bool:
        with self.repo.transaction() as con:
            row = con.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not row or not (row['state'] in ('DISPATCHING', 'DRAWING', 'PAUSING', 'STOPPING', 'RESUMING')
                               or row['state'] == 'PAUSED' and row['live_execution']):
                return False
            # Duplicated feedback is harmless, but it cannot advance checkpoints.
            if row['uncertain_stroke'] == stroke_id and row['current_pen'] == pen_id:
                return True
            pens = self._pens.get(job_id)
            if (not pens or type(stroke_id) is not int or stroke_id != row['completed_strokes'] + 1
                    or stroke_id > row['total_strokes'] or pen_id != pens[stroke_id - 1]
                    or row['uncertain_stroke'] is not None):
                return False
            fields = dict(uncertain_stroke=stroke_id, current_pen=pen_id,
                          message=f'Stroke {stroke_id} started; not committed')
            if row['state'] == 'DISPATCHING':
                fields['state'] = 'DRAWING'
            self.repo.patch(con, job_id, **fields)
            return True

    # [핵심 기능] 펜 이격 확인 뒤에만 완료 획을 DB에 확정
    def on_stroke_completed(self, job_id: str, stroke_id: int, *, pen_up_confirmed: bool) -> bool:
        if not pen_up_confirmed:
            return False
        with self.repo.transaction() as con:
            row = con.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not row or not (row['state'] in ('DRAWING', 'PAUSING', 'STOPPING', 'DISPATCHING', 'RESUMING')
                               or row['state'] == 'PAUSED' and row['live_execution']):
                return False
            if stroke_id <= row['completed_strokes'] and row['uncertain_stroke'] is None:
                return True  # duplicate feedback, not a new stroke
            if (type(stroke_id) is not int or stroke_id != row['completed_strokes'] + 1
                    or row['uncertain_stroke'] != stroke_id):
                return False
            fields = dict(completed_strokes=stroke_id, uncertain_stroke=None,
                          message=f'Stroke {stroke_id} committed after verified pen lift')
            if row['state'] == 'DISPATCHING':
                fields['state'] = 'DRAWING'
            self.repo.patch(con, job_id, **fields)
            return True

    def on_live_control(self, job_id: str, command: str) -> bool:
        """동일 실행의 드라이버 확인 후에만 중간 획을 보존한 상태를 확정합니다."""
        expected, target = {'PAUSE': ('PAUSING', 'PAUSED'),
                            'RESUME': ('RESUMING', 'DRAWING')}[command]
        with self.repo.transaction() as con:
            row = con.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not row or not row['live_execution'] or row['state'] != expected:
                return False
            self.repo.patch(con, job_id, state=target, error_code='', message=(
                '동일 획·모션을 유지한 일시정지' if command == 'PAUSE' else '일시정지한 모션의 남은 경로 재개'))
            return True

    # [핵심 기능] ROS Action 종료 결과가 실제 상태·완료 획·안전 확인과 일치하는지 검사
    def on_action_result(self, job_id: str, *, ros_status: int, success: bool, final_state: str,
                         completed_strokes: int, pen_up_confirmed: bool, error_code: str = '',
                         message: str = '') -> bool:
        """ROS GoalStatus: SUCCEEDED=4, CANCELED=5, ABORTED=6.

        Any mismatched result becomes RECOVERY_REQUIRED, never fake PAUSED/STOPPED.
        """
        with self.repo.transaction() as con:
            row = con.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not row or row['state'] not in ('DISPATCHING', 'DRAWING', 'PAUSING', 'PAUSED', 'RESUMING', 'STOPPING'):
                return False
            matches = type(completed_strokes) is int and completed_strokes == row['completed_strokes']
            if (ros_status == 4 and success and final_state == 'COMPLETED'
                    and matches and completed_strokes == row['total_strokes']
                    and row['uncertain_stroke'] is None and pen_up_confirmed):
                self.repo.patch(con, job_id, state='COMPLETED', message='Drawing completed, all pen lifts confirmed')
                return True
            if (ros_status == 5 and final_state == 'INTERRUPTED_SAFE' and row['state'] == 'PAUSING'
                    and not row['live_execution'] and not success and matches and pen_up_confirmed):
                code = 'UNCERTAIN_STROKE' if row['uncertain_stroke'] is not None else ''
                self.repo.patch(con, job_id, state='PAUSED', error_code=code,
                                message='Controller confirmed safe pause; ' +
                                ('stroke requires operator review' if code else 'resume permitted'))
                return True
            if (ros_status == 5 and final_state == 'INTERRUPTED_SAFE' and row['state'] == 'STOPPING'
                    and not success and matches and pen_up_confirmed):
                self.repo.patch(con, job_id, state='STOPPED',
                                error_code='UNCERTAIN_STROKE' if row['uncertain_stroke'] is not None else '',
                                message='Controller confirmed physical stop and pen lifted')
                return True
            self.repo.patch(con, job_id, state='STOPPED',
                            error_code=error_code or 'ACTION_FAILED',
                            message=(f'ros={ros_status} final={final_state} {error_code} {message}')[:480])
            return False

    # [핵심 기능] 통신 불명확·실패를 STOPPED로 정리해 다음 작업이 막히지 않게 함
    def mark_uncertain(self, job_id: str, code: str, message: str) -> bool:
        with self.repo.transaction() as con:
            row = con.execute('SELECT state FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not row or row['state'] in ('COMPLETED', 'STOPPED'):
                return False
            self.repo.patch(con, job_id, state='STOPPED',
                            error_code=code[:64], message=message[:480])
            return True
