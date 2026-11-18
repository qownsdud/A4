"""사용자가 제공한 실제 스크립트의 UI 입력·배치·펜 보존을 검사합니다."""

import hashlib
import json
from pathlib import Path
import pytest
from art_artwork_pipeline import draw_image_standalone as script
from art_artwork_pipeline.path_planner.drawing_plan import build_plan, write_job_plan


def test_ui_plan_preserves_mm_pen_layer_and_order(monkeypatch, tmp_path):
    cal = tmp_path / "plane.json"
    cal.write_text(
        json.dumps(
            dict(
                a=0.0,
                b=0.0,
                points=[
                    [float(x), float(y), 0.0, 0.0, 0.0, 0.0]
                    for x in (0, 105, 210)
                    for y in (0, 148.5, 297)
                ],
            )
        )
    )
    pens = tmp_path / "pens.json"
    pens.write_text(json.dumps([[0.0, 0.0, 10.0, 0.0, 0.0, 0.0]] * 3))
    stick = tmp_path / "stick.json"
    stick.write_text(json.dumps([0.0, 0.0, 10.0, 0.0, 0.0, 0.0]))
    settings = tmp_path / "control.json"
    settings.write_text(
        json.dumps(dict(validated=True, force_limits=[10.0] * 6, force_bias=[0.0] * 6))
    )
    monkeypatch.setenv("ART_MOTION_CONTROL_CONFIG", str(settings))
    monkeypatch.setattr(script, "CALIBRATION_FILE", str(cal))
    monkeypatch.setattr(script, "PENS_FILE", str(pens))
    monkeypatch.setattr(script, "STICK_FILE", str(stick))
    plan = build_plan(
        [dict(points=[[0, 0], [30, 20]]), dict(points=[[40, 40], [50, 60]])],
        80,
        80,
        job_id="INPUT",
        paper_size_mm=(297.0, 210.0),margin_mm=20.,
    )
    path = Path(write_job_plan(plan, tmp_path))
    captured = {}
    monkeypatch.setattr(
        script,
        "save_drawing_preview",
        lambda *a, **kw: (str(tmp_path / "preview.png"), None),
    )
    monkeypatch.setattr(
        script, "run_robot_drawing", lambda *args, **kwargs: captured.update(kwargs)
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    script.main(
        [
            "--input",
            str(path),
            "--ui-control",
            "--job-id",
            "INPUT",
            "--plan-sha256",
            digest,
        ]
    )
    records = captured["ordered_strokes"]
    assert [(r["stroke_id"], r["pen_id"], r["layer"]) for r in records] == [
        (r["stroke_id"], r["pen_id"], r["layer"]) for r in plan["strokes"]
    ]
    for original, record in zip(plan["strokes"], records):
        assert record["points_robot"] == [
            (210 - y, 297 - x) for x, y in original["points_mm"]
        ]
    with pytest.raises(ValueError, match="SHA"):
        script.main(
            [
                "--input",
                str(path),
                "--ui-control",
                "--job-id",
                "INPUT",
                "--plan-sha256",
                "0" * 64,
            ]
        )
