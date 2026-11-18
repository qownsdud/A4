"""plan_validator 단위 테스트."""

import json
from pathlib import Path
import pytest

from art_job_manager.plan_validator import PlanError, load_plan


def _write_plan(root: Path, job_id: str, payload: dict) -> Path:
    job_dir = root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "drawing_plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_v02(job_id: str = "JOB_001") -> dict:
    return {
        "schema_version": "0.2",
        "job_id": job_id,
        "unit": "mm",
        "coordinate_frame": "paper_top_left_x_right_y_down",
        "paper_mm": {"width": 297, "height": 210},
        "strokes": [
            {"stroke_id": 1, "execution_order": 0, "pen_id": "PEN_1", "points_mm": [[10.0, 20.0], [30.0, 40.0]]},
            {"stroke_id": 2, "execution_order": 1, "pen_id": "PEN_2", "points_mm": [[50.0, 60.0], [70.0, 80.0]]},
        ],
    }


def test_load_plan_valid_v02(tmp_path: Path):
    plan_path = _write_plan(tmp_path, "JOB_001", _valid_v02("JOB_001"))
    summary = load_plan("JOB_001", str(plan_path), plan_root=tmp_path)
    assert summary.stroke_count == 2
    assert summary.pen_ids == ("PEN_1", "PEN_2")
    assert len(summary.sha256) == 64


def test_load_plan_rejects_outside_root_and_mismatch(tmp_path: Path):
    outside = tmp_path.parent / "outside.json"
    outside.write_text(json.dumps(_valid_v02("JOB_001")), encoding="utf-8")
    try:
        with pytest.raises(PlanError, match="PLAN_OUTSIDE_ROOT_OR_BAD_TYPE"):
            load_plan("JOB_001", str(outside), plan_root=tmp_path)
    finally:
        outside.unlink(missing_ok=True)

    wrong_dir = _write_plan(tmp_path, "JOB_OTHER", _valid_v02("JOB_001"))
    with pytest.raises(PlanError, match="PLAN_JOB_DIRECTORY_MISMATCH"):
        load_plan("JOB_001", str(wrong_dir), plan_root=tmp_path)


def test_load_plan_rejects_out_of_range_coordinate(tmp_path: Path):
    bad = _valid_v02("JOB_002")
    bad["strokes"][0]["points_mm"][1] = [500.0, 10.0]
    path = _write_plan(tmp_path, "JOB_002", bad)
    with pytest.raises(PlanError, match="PLAN_COORDINATE_OUT_OF_RANGE"):
        load_plan("JOB_002", str(path), plan_root=tmp_path)
