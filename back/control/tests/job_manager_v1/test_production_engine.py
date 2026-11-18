# [파일 역할] 실제 JobManager 안전 상태 머신 단위 테스트
# [동작] SQLite·Goal 배차·피드백·일시정지·복구 등 핵심 분기를 검사합니다.
# [주의] Python 수준 검증이며 실물 로봇의 물리 안전 성능 검증은 아닙니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Safety and idempotency contract tests for REAL JobManager's core."""
import json
from pathlib import Path

from art_job_manager.production_engine import ProductionEngine


def make_plan(tmp_path, job='J1', count=3):
    root = tmp_path / 'plans'
    root.mkdir(exist_ok=True)
    plan = root / job / 'drawing_plan.json'
    plan.parent.mkdir(exist_ok=True)
    obj = {'schema_version': '0.1', 'job_id': job,
           'paper_mm': {'width': 210, 'height': 297},
           'strokes': [{'stroke_id': k, 'pen_id': 'PEN_1', 'points_mm': [[2, 4], [10, 20]]}
                       for k in range(1, count + 1)]}
    plan.write_text(json.dumps(obj), encoding='utf-8')
    return root, str(plan.resolve())


def engine(tmp_path):
    root, plan = make_plan(tmp_path)
    e = ProductionEngine(tmp_path / 'state.db', plan_root=root)
    return e, plan


# [핵심 기능] pytest: new job waits for real action 조건을 검증
def test_new_job_waits_for_real_action(tmp_path):
    e, plan = engine(tmp_path)
    assert e.create_job('J1', plan).state == 'QUEUED'
    assert e.status('J1')['completed_strokes'] == 0
    assert e.status('J1')['state'] == 'QUEUED'  # no automatic pretend-DRAWING
    e.close()


# [핵심 기능] pytest: no duplicate job id and only one active 조건을 검증
def test_no_duplicate_job_id_and_only_one_active(tmp_path):
    e, plan = engine(tmp_path)
    e.create_job('J1', plan)
    assert e.create_job('J1', plan).error_code == 'DUPLICATE_JOB'
    root, p2 = make_plan(tmp_path, 'J2')
    assert e.create_job('J2', p2).error_code == 'SYSTEM_BUSY'
    assert e.control_job('J1', 'CANCEL', 'cancel1').state == 'STOPPED'
    assert e.create_job('J2', p2).accepted
    e.close()


# [핵심 기능] pytest: dispatch and real start feedback 조건을 검증
def test_dispatch_and_real_start_feedback(tmp_path):
    e, plan = engine(tmp_path)
    e.create_job('J1', plan)
    d = e.prepare_dispatch('J1')
    assert d.start_stroke_id == 1 and d.plan_path == plan and len(d.plan_sha256) == 64
    assert e.status('J1')['state'] == 'DISPATCHING'
    assert e.on_controller_started('J1')
    assert e.status('J1')['state'] == 'DRAWING'
    e.close()


# [핵심 기능] pytest: checkpoints only after pen up 조건을 검증
def test_checkpoints_only_after_pen_up(tmp_path):
    e, plan = engine(tmp_path)
    e.create_job('J1', plan)
    e.prepare_dispatch('J1')
    assert e.on_stroke_started('J1', 1, 'PEN_1')
    assert e.status('J1')['uncertain_stroke'] == 1
    assert not e.on_stroke_completed('J1', 1, pen_up_confirmed=False)
    assert e.status('J1')['completed_strokes'] == 0
    assert e.on_stroke_completed('J1', 1, pen_up_confirmed=True)
    assert e.status('J1')['completed_strokes'] == 1
    assert e.status('J1')['uncertain_stroke'] is None
    e.close()


# [핵심 기능] pytest: wrong stroke or pen rejected 조건을 검증
def test_wrong_stroke_or_pen_rejected(tmp_path):
    e, plan = engine(tmp_path)
    e.create_job('J1', plan)
    e.prepare_dispatch('J1')
    assert not e.on_stroke_started('J1', 2, 'PEN_1')
    assert not e.on_stroke_started('J1', 1, 'PEN_BAD')
    assert e.on_stroke_started('J1', 1, 'PEN_1')
    assert not e.on_stroke_completed('J1', 2, pen_up_confirmed=True)
    e.close()


# [핵심 기능] pytest: pause waits for safe canceled result 조건을 검증
def test_pause_waits_for_safe_canceled_result(tmp_path):
    e, plan = engine(tmp_path)
    e.create_job('J1', plan)
    e.prepare_dispatch('J1')
    e.on_controller_started('J1')
    assert e.control_job('J1', 'PAUSE', 'p1').state == 'PAUSING'
    assert e.status('J1')['state'] == 'PAUSING'
    assert e.on_action_result('J1', ros_status=5, success=False,
                              final_state='INTERRUPTED_SAFE', completed_strokes=0,
                              pen_up_confirmed=True)
    assert e.status('J1')['state'] == 'PAUSED'
    e.close()


# [핵심 기능] pytest: resume creates new goal at next stroke 조건을 검증
def test_resume_creates_new_goal_at_next_stroke(tmp_path):
    e, plan = engine(tmp_path)
    e.create_job('J1', plan)
    e.prepare_dispatch('J1')
    e.on_controller_started('J1')
    e.on_stroke_started('J1', 1, 'PEN_1')
    e.on_stroke_completed('J1', 1, pen_up_confirmed=True)
    e.control_job('J1', 'PAUSE', 'p1')
    e.on_action_result('J1', ros_status=5, success=False,
                       final_state='INTERRUPTED_SAFE', completed_strokes=1,
                       pen_up_confirmed=True)
    assert e.control_job('J1', 'RESUME', 'r1').state == 'QUEUED'
    assert e.prepare_dispatch('J1').start_stroke_id == 2
    e.close()


# [핵심 기능] pytest: uncertain stroke cannot resume even after safe pause 조건을 검증
def test_uncertain_stroke_cannot_resume_even_after_safe_pause(tmp_path):
    e, plan = engine(tmp_path)
    e.create_job('J1', plan)
    e.prepare_dispatch('J1')
    e.on_controller_started('J1')
    e.on_stroke_started('J1', 1, 'PEN_1')
    e.control_job('J1', 'PAUSE', 'p1')
    assert e.on_action_result('J1', ros_status=5, success=False,
                              final_state='INTERRUPTED_SAFE', completed_strokes=0,
                              pen_up_confirmed=True)
    assert e.status('J1')['error_code'] == 'UNCERTAIN_STROKE'
    assert e.control_job('J1', 'RESUME', 'r1').error_code == 'UNCERTAIN_STROKE'
    e.close()


# [핵심 기능] pytest: cancel waits for safe result 조건을 검증
def test_cancel_waits_for_safe_result(tmp_path):
    e, plan = engine(tmp_path)
    e.create_job('J1', plan)
    e.prepare_dispatch('J1')
    assert e.control_job('J1', 'CANCEL', 'c1').state == 'STOPPING'
    assert e.status('J1')['state'] == 'STOPPING'
    assert e.on_action_result('J1', ros_status=5, success=False,
                              final_state='INTERRUPTED_SAFE', completed_strokes=0,
                              pen_up_confirmed=True)
    assert e.status('J1')['state'] == 'STOPPED'
    e.close()


# [핵심 기능] pytest: unverified cancel result requires recovery 조건을 검증
def test_unverified_cancel_result_requires_recovery(tmp_path):
    e, plan = engine(tmp_path)
    e.create_job('J1', plan)
    e.prepare_dispatch('J1')
    e.control_job('J1', 'CANCEL', 'c1')
    assert not e.on_action_result('J1', ros_status=5, success=False,
                                  final_state='INTERRUPTED_SAFE', completed_strokes=0,
                                  pen_up_confirmed=False)
    assert e.status('J1')['state'] == 'RECOVERY_REQUIRED'
    e.close()


# [핵심 기능] pytest: completion only after action success and all checkpoints 조건을 검증
def test_completion_only_after_action_success_and_all_checkpoints(tmp_path):
    e, plan = engine(tmp_path)
    e.create_job('J1', plan)
    e.prepare_dispatch('J1')
    e.on_controller_started('J1')
    for k in (1, 2, 3):
        assert e.on_stroke_started('J1', k, 'PEN_1')
        assert e.on_stroke_completed('J1', k, pen_up_confirmed=True)
    assert e.status('J1')['state'] == 'DRAWING'  # no fabricated completion
    assert e.on_action_result('J1', ros_status=4, success=True, final_state='COMPLETED',
                              completed_strokes=3, pen_up_confirmed=True)
    assert e.status('J1')['state'] == 'COMPLETED'
    e.close()


# [핵심 기능] pytest: goal result mismatch blocks new jobs 조건을 검증
def test_goal_result_mismatch_blocks_new_jobs(tmp_path):
    e, plan = engine(tmp_path)
    e.create_job('J1', plan)
    e.prepare_dispatch('J1')
    assert not e.on_action_result('J1', ros_status=4, success=True, final_state='COMPLETED',
                                  completed_strokes=3, pen_up_confirmed=True)
    assert e.status('J1')['state'] == 'RECOVERY_REQUIRED'
    _, other = make_plan(tmp_path, 'J2')
    assert e.create_job('J2', other).error_code == 'SYSTEM_BUSY'
    e.close()


# [핵심 기능] pytest: changed plan prevents resume and dispatch 조건을 검증
def test_changed_plan_prevents_resume_and_dispatch(tmp_path):
    e, path = engine(tmp_path)
    e.create_job('J1', path)
    obj = json.loads(Path(path).read_text())
    obj['strokes'][0]['points_mm'][0] = [5, 6]
    Path(path).write_text(json.dumps(obj))
    assert e.prepare_dispatch('J1') is None
    assert e.status('J1')['error_code'] == 'PLAN_CHANGED'
    e.close()


# [핵심 기능] pytest: request id idempotent 조건을 검증
def test_request_id_idempotent(tmp_path):
    e, path = engine(tmp_path)
    e.create_job('J1', path)
    e.prepare_dispatch('J1')
    first = e.control_job('J1', 'PAUSE', 'req1')
    assert first.accepted
    assert e.control_job('J1', 'PAUSE', 'req1').accepted
    assert e.control_job('J1', 'CANCEL', 'req1').error_code == 'REQUEST_ID_CONFLICT'
    e.close()


# [핵심 기능] pytest: restart never auto dispatches inflight job 조건을 검증
def test_restart_never_auto_dispatches_inflight_job(tmp_path):
    e, path = engine(tmp_path)
    e.create_job('J1', path)
    e.prepare_dispatch('J1')
    e.close()
    root = tmp_path / 'plans'
    restarted = ProductionEngine(tmp_path / 'state.db', plan_root=root)
    assert restarted.status('J1')['state'] == 'RECOVERY_REQUIRED'
    assert restarted.prepare_dispatch('J1') is None
    assert restarted.control_job('J1', 'RESUME', 'r1').error_code == 'INVALID_TRANSITION'
    restarted.close()


# [핵심 기능] pytest: no automatic replay during uncertain resume 조건을 검증
def test_no_automatic_replay_during_uncertain_resume(tmp_path):
    e, path = engine(tmp_path)
    e.create_job('J1', path)
    e.prepare_dispatch('J1')
    e.on_stroke_started('J1', 1, 'PEN_1')
    e.control_job('J1', 'PAUSE', 'p1')
    e.on_action_result('J1', ros_status=5, success=False,
                       final_state='INTERRUPTED_SAFE', completed_strokes=0, pen_up_confirmed=True)
    assert not e.control_job('J1', 'RESUME', 'r1').accepted
    e.close()
