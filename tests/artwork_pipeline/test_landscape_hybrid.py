"""가로 용지와 실제 Canny 합성을 외부 모델 다운로드 없이 검증합니다."""

import numpy as np
from PIL import Image
import pytest
from art_artwork_pipeline.paper import fit_landscape_preview, layout, LANDSCAPE
from art_artwork_pipeline.lineart.lineart_mfl_ld import (
    compose_face_lineart,
    LineartMflLdConfig,
    _ensure_face_model,
)
from art_artwork_pipeline.path_planner.drawing_plan import build_plan, write_job_plan
from art_artwork_pipeline.plan import load_plan


def test_landscape_margin_and_plan_job_manager(tmp_path):
    image = fit_landscape_preview(Image.new("RGB", (771, 510), "black"))
    assert image.size == (891, 630)
    assert image.getpixel((59, 60)) == (255, 255, 255)
    assert image.getpixel((60, 60)) == (0, 0, 0)
    spec = layout(LANDSCAPE, True)
    assert spec["artwork"][1] + spec["artwork"][3] < spec["text_bounds"][1]
    plan = build_plan(
        [dict(points=[[0, 0], [770, 509]])],
        771,
        510,
        job_id="LANDSCAPE",
        paper_size_mm=(297.0, 210.0),
        margin_mm=20.0,
    )
    path = write_job_plan(plan, tmp_path)
    assert load_plan("LANDSCAPE", str(path), plan_root=tmp_path).stroke_count > 0


def test_face_mask_keeps_dl_outside_and_canny_inside(tmp_path):
    rgb = np.full((64, 64, 3), 255, np.uint8)
    rgb[20:45, 20:45] = 0
    dl = np.full((64, 64), 73, np.uint8)
    mask = np.zeros((64, 64), np.uint8)
    mask[10:55, 10:55] = 255
    result = np.array(compose_face_lineart(rgb, dl, mask, LineartMflLdConfig()))
    assert np.all(result[mask == 0] == 73)
    assert np.any(result[mask > 0] == 0) and np.any(result[mask > 0] == 255)
    with pytest.raises(FileNotFoundError):
        _ensure_face_model(tmp_path / "missing.task", "unused")
