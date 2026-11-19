"""한글·영문·숫자·특수문자 캘리그라피 경로 생성 및 파이프라인 연동을 검증합니다."""

import json
from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from art_artwork_pipeline.calligraphy.generator import generate_strokes
from art_artwork_pipeline.paper import LANDSCAPE, layout
from art_artwork_pipeline.pipeline_runner import prepare_artwork, save_photo


def test_calligraphy_supports_korean_english_numbers_and_symbols():
    placement = layout(LANDSCAPE, True)
    for sample in ("안녕! Hi ★ 2026", "가나다라마바사", "Hello, World?!", "♥♪☆@#&", "OOOOO"):
        strokes = generate_strokes(
            sample,
            origin=placement["text_origin"],
            bounds_mm=placement["text_bounds"],
            paper_size_mm=placement["size"],
        )
        assert len(strokes) > 0, f"획이 비어 있음: {sample}"
        xs = [x for st in strokes for x, _ in st["points_mm"]]
        assert abs(min(xs) - placement["text_bounds"][0]) < 1.0
        assert max(xs) <= placement["text_bounds"][2] + 1e-6
        for st in strokes:
            assert st["layer"] == "calligraphy"
            assert len(st["points_mm"]) >= 2
            for x, y in st["points_mm"]:
                assert 0 <= x <= placement["size"][0]
                assert 0 <= y <= placement["size"][1]

    # 원(O) 5개는 각각 1개의 연속 폐곡선으로만 추출되어 불필요한 점이 찍히지 않아야 하며, 왼쪽부터 순서대로 진행해야 함
    circle_strokes = generate_strokes(
        "OOOOO",
        origin=placement["text_origin"],
        bounds_mm=placement["text_bounds"],
        paper_size_mm=placement["size"],
    )
    assert len(circle_strokes) == 5
    centers_x = [sum(p[0] for p in st["points_mm"]) / len(st["points_mm"]) for st in circle_strokes]
    assert centers_x == sorted(centers_x)


def test_calligraphy_rejects_control_chars_and_handles_blank():
    assert generate_strokes("") == []
    assert generate_strokes("   ") == []
    with pytest.raises(ValueError):
        generate_strokes("안녕\n줄바꿈")


def test_prepare_artwork_plan_with_korean_and_symbols(monkeypatch, tmp_path):
    monkeypatch.setenv("ART_JOB_PLAN_ROOT", str(tmp_path))
    monkeypatch.setenv("ART_LINEART_METHOD", "cv")

    img = Image.new("RGB", (200, 140), "white")
    ImageDraw.Draw(img).rectangle((30, 30, 170, 110), outline="black", width=3)
    photo_path = tmp_path / "src.png"
    img.save(photo_path)

    job_id = "CALLIGRAPHY_UNI_01"
    saved = save_photo(job_id, photo_path.read_bytes(), root=tmp_path)
    line_res = prepare_artwork(
        job_id,
        stage="LINEART",
        input_path=str((saved / "photo.png").resolve()),
        paper=LANDSCAPE,
        method="cv",
        root=tmp_path,
    )
    meta_path = Path(line_res["lineart_path"]).parent / "job_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["confirmed"] = True
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    plan_res = prepare_artwork(
        job_id,
        stage="PLAN",
        input_path=line_res["lineart_path"],
        text="안녕! Hello ★",
        paper=LANDSCAPE,
        root=tmp_path,
    )
    plan = json.loads(Path(plan_res["plan_path"]).read_text(encoding="utf-8"))
    assert any(st["layer"] == "calligraphy" for st in plan["strokes"])
