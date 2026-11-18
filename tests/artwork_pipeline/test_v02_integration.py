"""Pure Python Phase3-to-JobManager contract tests; no ROS or robot motion."""
import json
from pathlib import Path

import pytest

from art_artwork_pipeline.path_planner.drawing_plan import FRAME, build_plan, validate_plan, write_job_plan
from art_artwork_pipeline.path_planner.path_optimizer import optimize_plan
from art_artwork_pipeline.plan import PlanError, load_plan


def sample_plan(job_id='JOB_V02_001'):
    strokes = [
        {'points': [[0, 0], [10, 10], [20, 20]]},
        {'points': [[30, 40], [50, 70]]},
        {'points': [[80, 20], [99, 90]]},
    ]
    return build_plan(strokes, 100, 100, job_id=job_id, seed=42)


def test_v02_full_contract_and_immutability(tmp_path):
    root = tmp_path / 'plans'
    p = sample_plan()
    assert p['schema_version'] == '0.2'
    assert p['coordinate_frame'] == FRAME
    assert [s['stroke_id'] for s in p['strokes']] == [1, 2, 3]
    target = write_job_plan(p, root)
    info = load_plan(p['job_id'], str(target), plan_root=root)
    assert info.stroke_count == 3
    assert set(info.pen_ids) <= {'PEN_1', 'PEN_2', 'PEN_3'}
    assert info.sha256 and len(info.sha256) == 64
    with pytest.raises(FileExistsError):
        write_job_plan(p, root)
    assert load_plan(p['job_id'], str(target), plan_root=root).sha256 == info.sha256


def test_v02_optimizer_to_job_manager(tmp_path):
    root = tmp_path / 'plans'
    plan = sample_plan('JOB_OPT_002')
    optimized = optimize_plan(plan, backend='opencv', max_strokes=None, curve_step_mm=0)
    assert validate_plan(optimized)
    target = write_job_plan(optimized, root)
    summary = load_plan('JOB_OPT_002', str(target), plan_root=root)
    assert summary.stroke_count == len(optimized['strokes'])


@pytest.mark.parametrize('key,value,code', [
    ('coordinate_frame', 'paper_bottom_left_x_right_y_up', 'PLAN_COORDINATE_FRAME_INVALID'),
    ('unit', 'px', 'PLAN_COORDINATE_FRAME_INVALID'),
])
def test_bad_frame_or_unit_rejected_by_job_manager(tmp_path, key, value, code):
    root = tmp_path / 'plans'
    plan = sample_plan()
    plan[key] = value
    with pytest.raises(ValueError):
        validate_plan(plan)
    job_dir = root / plan['job_id']
    job_dir.mkdir(parents=True)
    target = job_dir / 'drawing_plan.json'
    target.write_text(json.dumps(plan))
    with pytest.raises(PlanError, match=code):
        load_plan(plan['job_id'], str(target), plan_root=root)


def test_invalid_pen_grid_or_execution_order(tmp_path):
    root = tmp_path / 'plans'
    for defect in ('pen', 'grid', 'order'):
        plan = sample_plan('JOB_' + defect)
        if defect == 'pen':
            plan['strokes'][0]['pen_id'] = 'pen_1'
        elif defect == 'grid':
            plan['strokes'][0]['grid_id'] = 99
        else:
            plan['strokes'][0]['execution_order'] = 2
        with pytest.raises(ValueError):
            validate_plan(plan)
        job_dir = root / plan['job_id']
        job_dir.mkdir(parents=True)
        path = job_dir / 'drawing_plan.json'
        path.write_text(json.dumps(plan))
        with pytest.raises(PlanError):
            load_plan(plan['job_id'], str(path), plan_root=root)


def test_job_id_path_traversal_rejected():
    with pytest.raises(ValueError):
        sample_plan('../escape')


def test_legacy_v01_accepted_and_unrelated_v10_rejected(tmp_path):
    root = tmp_path / 'plans'
    job_dir = root / 'JOB_LEGACY'
    job_dir.mkdir(parents=True)
    path = job_dir / 'drawing_plan.json'
    old = {'schema_version': '0.1', 'job_id': 'JOB_LEGACY',
           'paper_mm': {'width': 210, 'height': 297},
           'strokes': [{'stroke_id': 1, 'pen_id': 'PEN_1', 'points_mm': [[5, 5], [10, 10]]}]}
    path.write_text(json.dumps(old))
    assert load_plan('JOB_LEGACY', str(path), plan_root=root).stroke_count == 1
    old['schema_version'] = '1.0'
    path.write_text(json.dumps(old))
    with pytest.raises(PlanError, match='PLAN_SCHEMA_OR_ID_MISMATCH'):
        load_plan('JOB_LEGACY', str(path), plan_root=root)
