"""DrawingPlan JSON 파일의 경로, 스키마, 좌표, SHA-256 무결성을 검증합니다."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path


class PlanError(ValueError):
    """DrawingPlan 검증 실패 시 발생하는 오류 코드 예외입니다."""


@dataclass(frozen=True)
class PlanSummary:
    """검증을 통과한 DrawingPlan의 요약 정보입니다."""

    path: str
    sha256: str
    stroke_count: int
    pen_ids: tuple[str, ...]


def default_plan_root() -> Path:
    """ART_JOB_PLAN_ROOT 또는 현재 A4/data/jobs 경로를 반환합니다."""
    env_root = os.environ.get("ART_JOB_PLAN_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "ros2_ws":
            return (parent.parent / "data/jobs").resolve()
    return (Path.cwd() / "data/jobs").resolve()


def _parse_json_strict(raw: bytes) -> dict:
    try:
        obj = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")),
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise PlanError("PLAN_BAD_JSON") from exc
    if not isinstance(obj, dict):
        raise PlanError("PLAN_BAD_JSON")
    return obj


def _validate_points(points: object, width: float, height: float) -> None:
    if not isinstance(points, list) or len(points) < 2:
        raise PlanError("PLAN_STROKE_POINTS_INVALID")
    for pt in points:
        if not isinstance(pt, list) or len(pt) != 2:
            raise PlanError("PLAN_STROKE_POINTS_INVALID")
        x, y = pt
        if type(x) not in (int, float) or type(y) not in (int, float):
            raise PlanError("PLAN_STROKE_POINTS_INVALID")
        if not (math.isfinite(x) and math.isfinite(y) and 0 <= x <= width and 0 <= y <= height):
            raise PlanError("PLAN_COORDINATE_OUT_OF_RANGE")


def load_plan(
    job_id: str,
    plan_path: str,
    *,
    plan_root: Path | None = None,
    max_bytes: int = 5_000_000,
) -> PlanSummary:
    """작업 디렉터리 내 DrawingPlan JSON을 검증하고 SHA-256 및 획 요약을 반환합니다."""
    if not plan_path or not Path(plan_path).is_absolute():
        raise PlanError("PLAN_PATH_NOT_ABSOLUTE")
    target_root = plan_root if plan_root is not None else default_plan_root()
    try:
        root = target_root.expanduser().resolve(strict=True)
        path = Path(plan_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PlanError("PLAN_NOT_FOUND") from exc

    if path == root or root not in path.parents or not path.is_file() or path.suffix.lower() != ".json":
        raise PlanError("PLAN_OUTSIDE_ROOT_OR_BAD_TYPE")
    if path.parent.name != job_id:
        raise PlanError("PLAN_JOB_DIRECTORY_MISMATCH")

    try:
        if path.stat().st_size > max_bytes:
            raise PlanError("PLAN_TOO_LARGE")
        data = path.read_bytes()
    except OSError as exc:
        raise PlanError("PLAN_READ_FAILED") from exc
    if len(data) > max_bytes:
        raise PlanError("PLAN_TOO_LARGE")

    obj = _parse_json_strict(data)
    schema = obj.get("schema_version")
    if schema not in ("0.1", "0.2") or obj.get("job_id") != job_id:
        raise PlanError("PLAN_SCHEMA_OR_ID_MISMATCH")

    grid = obj.get("grid")
    if schema == "0.2":
        if obj.get("unit") != "mm" or obj.get("coordinate_frame") != "paper_top_left_x_right_y_down":
            raise PlanError("PLAN_COORDINATE_FRAME_INVALID")
        if grid is not None:
            if not isinstance(grid, dict) or grid.get("type") != "4x4":
                raise PlanError("PLAN_GRID_INVALID")
            cells = grid.get("cell_pen_ids")
            if not isinstance(cells, list) or len(cells) != 16 or any(p not in ("PEN_1", "PEN_2", "PEN_3") for p in cells):
                raise PlanError("PLAN_GRID_INVALID")

    paper = obj.get("paper_mm")
    if not isinstance(paper, dict) or (paper.get("width"), paper.get("height")) not in ((210, 297), (297, 210)):
        raise PlanError("PLAN_A4_REQUIRED")
    if schema == "0.1" and (paper.get("width"), paper.get("height")) != (210, 297):
        raise PlanError("PLAN_A4_PORTRAIT_REQUIRED")

    strokes = obj.get("strokes")
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 100_000:
        raise PlanError("PLAN_STROKES_INVALID")

    pens: list[str] = []
    width, height = float(paper["width"]), float(paper["height"])
    for expected, stroke in enumerate(strokes, 1):
        if not isinstance(stroke, dict) or type(stroke.get("stroke_id")) is not int or stroke["stroke_id"] != expected:
            raise PlanError("PLAN_STROKE_ORDER_INVALID")
        pen_id = stroke.get("pen_id")
        if not isinstance(pen_id, str) or not 1 <= len(pen_id) <= 64:
            raise PlanError("PLAN_PEN_ID_INVALID")
        if schema == "0.2":
            if pen_id not in ("PEN_1", "PEN_2", "PEN_3", "PEN_4"):
                raise PlanError("PLAN_PEN_ID_INVALID")
            if "execution_order" in stroke and (type(stroke["execution_order"]) is not int or stroke["execution_order"] != expected - 1):
                raise PlanError("PLAN_STROKE_ORDER_INVALID")
            if "grid_id" in stroke:
                gid = stroke["grid_id"]
                if grid is None or type(gid) is not int or not 0 <= gid < 16 or grid["cell_pen_ids"][gid] != pen_id:
                    raise PlanError("PLAN_GRID_INVALID")
        _validate_points(stroke.get("points_mm"), width, height)
        pens.append(pen_id)

    return PlanSummary(
        path=str(path),
        sha256=hashlib.sha256(data).hexdigest(),
        stroke_count=len(strokes),
        pen_ids=tuple(pens),
    )
