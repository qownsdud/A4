# [파일 역할] 이전 JobManager/ROS 연동 테스트
# [동작] 구형 시뮬레이션 상태 머신 및 Bridge ROS 계약의 회귀를 검사합니다.
# [주의] ROS 2가 없는 환경에서는 일부 자동 건너뛸 수 있습니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Standalone SQLite/state-machine tests; no ROS 2 or robot needed."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from art_job_manager.job_engine import JobEngine


def plan(root: Path, job_id='JOB_001', count=3):
    target = root / job_id / 'drawing_plan.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        'schema_version': '0.1', 'job_id': job_id,
        'paper_mm': {'width': 210, 'height': 297},
        'strokes': [{'stroke_id': i, 'pen_id': 'PEN_1', 'points_mm': [[5, 5], [10, 10]]}
                    for i in range(1, count + 1)],
    }), encoding='utf-8')
    return str(target.resolve())


@pytest.fixture
def context(tmp_path):
    root = tmp_path / 'plans'
    root.mkdir()
    db = tmp_path / 'data' / 'jobs.db'
    return db, root


# [핵심 기능] pytest: default queues without hardware 조건을 검증
def test_default_queues_without_hardware(context):
    db, root = context
    engine = JobEngine(db, plan_root=root)
    path = plan(root)
    got = engine.create_job('JOB_001', path)
    assert got.accepted and got.state == 'QUEUED'
    assert engine.status('JOB_001')['completed_strokes'] == 0
    engine.simulate_tick()  # no simulation => no motion
    assert engine.status('JOB_001')['state'] == 'QUEUED'
    assert engine.control_job('JOB_001', 'PAUSE', 'pause1').error_code == 'INVALID_TRANSITION'
    engine.close()


# [핵심 기능] pytest: invalid id and missing or untrusted plan 조건을 검증
def test_invalid_id_and_missing_or_untrusted_plan(context, tmp_path):
    db, root = context
    engine = JobEngine(db, plan_root=root)
    assert engine.create_job('BAD/ID', '/tmp/nowhere.json').error_code == 'INVALID_JOB_ID'
    assert engine.create_job('JOB_001', '/tmp/missing.json').error_code == 'PLAN_NOT_FOUND'
    outside = tmp_path / 'outside'
    outside.mkdir()
    assert engine.create_job('JOB_001', plan(outside)).error_code == 'PLAN_OUTSIDE_ROOT_OR_BAD_TYPE'
    engine.close()


# [핵심 기능] pytest: wrong schema and invalid coordinate 조건을 검증
def test_wrong_schema_and_invalid_coordinate(context):
    db, root = context
    engine = JobEngine(db, plan_root=root)
    path = Path(plan(root))
    obj = json.loads(path.read_text())
    obj['strokes'][0]['points_mm'][0][0] = -1
    path.write_text(json.dumps(obj))
    assert engine.create_job('JOB_001', str(path)).error_code == 'PLAN_COORD_OUT_OF_A4'
    obj['strokes'][0]['points_mm'][0][0] = 5
    obj['job_id'] = 'OTHER'
    path.write_text(json.dumps(obj))
    assert engine.create_job('JOB_001', str(path)).error_code == 'PLAN_SCHEMA_OR_ID_MISMATCH'
    engine.close()


# [핵심 기능] pytest: duplicate job and only one active job 조건을 검증
def test_duplicate_job_and_only_one_active_job(context):
    db, root = context
    engine = JobEngine(db, plan_root=root)
    p1, p2 = plan(root), plan(root, 'JOB_002')
    assert engine.create_job('JOB_001', p1).accepted
    assert engine.create_job('JOB_001', p1).error_code == 'DUPLICATE_JOB'
    assert engine.create_job('JOB_002', p2).error_code == 'SYSTEM_BUSY'
    assert engine.control_job('JOB_001', 'CANCEL', 'C1').state == 'STOPPED'
    assert engine.create_job('JOB_002', p2).accepted
    engine.close()


# [핵심 기능] pytest: simulated pause resume and complete 조건을 검증
def test_simulated_pause_resume_and_complete(context):
    db, root = context
    engine = JobEngine(db, plan_root=root, simulation=True)
    p = plan(root, count=3)
    assert engine.create_job('JOB_001', p).state == 'DRAWING'
    engine.simulate_tick()
    assert engine.status('JOB_001')['completed_strokes'] == 1
    resp = engine.control_job('JOB_001', 'PAUSE', 'P1')
    assert resp.accepted and resp.state == 'PAUSING'
    assert engine.status('JOB_001')['state'] == 'PAUSING'
    assert engine.status('JOB_001')['completed_strokes'] == 1
    engine.simulate_tick()
    assert engine.status('JOB_001')['state'] == 'PAUSED'
    assert engine.status('JOB_001')['completed_strokes'] == 1
    resp = engine.control_job('JOB_001', 'RESUME', 'R1')
    assert resp.accepted and resp.state == 'DRAWING'
    engine.simulate_tick()
    engine.simulate_tick()
    assert engine.status('JOB_001')['state'] == 'COMPLETED'
    assert engine.status('JOB_001')['completed_strokes'] == 3
    engine.close()


# [핵심 기능] pytest: cancel ack is not immediate stop 조건을 검증
def test_cancel_ack_is_not_immediate_stop(context):
    db, root = context
    engine = JobEngine(db, plan_root=root, simulation=True)
    engine.create_job('JOB_001', plan(root))
    response = engine.control_job('JOB_001', 'CANCEL', 'C1')
    assert response.state == 'STOPPING'
    assert engine.status('JOB_001')['state'] == 'STOPPING'
    engine.simulate_tick()
    assert engine.status('JOB_001')['state'] == 'STOPPED'
    engine.close()


# [핵심 기능] pytest: control idempotency and conflict persist 조건을 검증
def test_control_idempotency_and_conflict_persist(context):
    db, root = context
    p = plan(root)
    a = JobEngine(db, plan_root=root, simulation=True)
    assert a.create_job('JOB_001', p).accepted
    first = a.control_job('JOB_001', 'PAUSE', 'p1')
    assert first.accepted and first.state == 'PAUSING'
    replay = a.control_job('JOB_001', 'PAUSE', 'p1')
    assert replay.accepted and replay.state == 'PAUSING' and 'replay' in replay.message
    assert a.control_job('JOB_001', 'CANCEL', 'p1').error_code == 'REQUEST_ID_CONFLICT'
    a.close()
    b = JobEngine(db, plan_root=root, simulation=True)
    assert b.status('JOB_001')['state'] == 'RECOVERY_REQUIRED'
    replay_after_restart = b.control_job('JOB_001', 'PAUSE', 'p1')
    assert replay_after_restart.accepted and replay_after_restart.state == 'RECOVERY_REQUIRED'
    b.close()


# [핵심 기능] pytest: only pen lift confirms checkpoint 조건을 검증
def test_only_pen_lift_confirms_checkpoint(context):
    db, root = context
    engine = JobEngine(db, plan_root=root)
    engine.create_job('JOB_001', plan(root))
    assert engine.on_controller_started('JOB_001')
    assert engine.on_stroke_started('JOB_001', 1, 'PEN_1')
    assert engine.status('JOB_001')['uncertain_stroke'] == 1
    assert not engine.on_stroke_finished('JOB_001', 1, pen_lift_confirmed=False)
    assert engine.status('JOB_001')['completed_strokes'] == 0
    assert engine.on_stroke_finished('JOB_001', 1, pen_lift_confirmed=True)
    assert engine.status('JOB_001')['completed_strokes'] == 1
    assert engine.status('JOB_001')['uncertain_stroke'] is None
    engine.close()


# [핵심 기능] pytest: interrupted stroke requires operator review after restart 조건을 검증
def test_interrupted_stroke_requires_operator_review_after_restart(context):
    db, root = context
    engine = JobEngine(db, plan_root=root)
    engine.create_job('JOB_001', plan(root))
    assert engine.on_controller_started('JOB_001')
    assert engine.on_stroke_started('JOB_001', 1, 'PEN_1')
    engine.close()
    recovered = JobEngine(db, plan_root=root, simulation=True)
    assert recovered.status('JOB_001')['state'] == 'RECOVERY_REQUIRED'
    assert recovered.status('JOB_001')['uncertain_stroke'] == 1
    assert not recovered.control_job('JOB_001', 'RESUME', 'R1').accepted
    recovered.simulate_tick()
    assert recovered.status('JOB_001')['completed_strokes'] == 0
    recovered.close()


# [핵심 기능] pytest: resume rejects modified plan 조건을 검증
def test_resume_rejects_modified_plan(context):
    db, root = context
    engine = JobEngine(db, plan_root=root, simulation=True)
    path = Path(plan(root))
    engine.create_job('JOB_001', str(path))
    engine.control_job('JOB_001', 'PAUSE', 'P1')
    engine.simulate_tick()
    obj = json.loads(path.read_text())
    obj['strokes'][0]['points_mm'][0] = [6, 6]
    path.write_text(json.dumps(obj))
    assert engine.control_job('JOB_001', 'RESUME', 'R1').error_code == 'PLAN_CHANGED'
    engine.close()


# [핵심 기능] pytest: simulator does not auto complete uncertain stroke 조건을 검증
def test_simulator_does_not_auto_complete_uncertain_stroke(context):
    db, root = context
    engine = JobEngine(db, plan_root=root, simulation=True)
    engine.create_job('JOB_001', plan(root))
    assert engine.on_stroke_started('JOB_001', 1, 'PEN_1')
    engine.simulate_tick()
    assert engine.status('JOB_001')['state'] == 'RECOVERY_REQUIRED'
    assert engine.status('JOB_001')['uncertain_stroke'] == 1
    engine.close()


# [핵심 기능] pytest: missing job and command 조건을 검증
def test_missing_job_and_command(context):
    db, root = context
    engine = JobEngine(db, plan_root=root)
    assert engine.control_job('NOT_FOUND', 'PAUSE', 'P1').error_code == 'JOB_NOT_FOUND'
    engine.create_job('JOB_001', plan(root))
    assert engine.control_job('JOB_001', 'START', 'S1').error_code == 'UNKNOWN_COMMAND'
    assert engine.control_job('JOB_001', 'PAUSE', 'p/1').error_code == 'INVALID_ID'
    engine.close()
