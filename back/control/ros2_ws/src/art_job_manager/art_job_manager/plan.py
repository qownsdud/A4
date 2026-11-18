# [파일 역할] DrawingPlan JSON 검증기
# [동작] 경로·job_id·schema_version·A4 mm 좌표·획 순서 등을 검사하고 SHA-256을 계산합니다.
# [주의] 픽셀 경로 JSON이 아니라 로봇용 변환 완료된 drawing_plan.json을 받습니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Validate job-specific DrawingPlan JSON before accepting a job.

TEAM_SYNC(ArtworkPipeline): schema v0.2 defines an explicit paper frame. The upstream pipeline
must write an immutable, per-job plan under the configured ART_JOB_PLAN_ROOT.
No actual robot coordinates/motion code should consume this schema until the
paper frame, origin, dimensions, units and pen mapping are approved.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class PlanSummary:
    path: str
    sha256: str
    stroke_count: int
    pen_ids: tuple[str, ...]


# [핵심 기능] DrawingPlan JSON의 안전 규칙을 검사하고 SHA·획 정보 생성
def load_plan(job_id: str, plan_path: str, *, plan_root: Path, max_bytes: int = 5_000_000) -> PlanSummary:
    if not plan_path or not Path(plan_path).is_absolute():
        raise PlanError('PLAN_PATH_NOT_ABSOLUTE')
    try:
        root = plan_root.expanduser().resolve(strict=True)
        path = Path(plan_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PlanError('PLAN_NOT_FOUND') from exc
    if path == root or root not in path.parents or not path.is_file() or path.suffix.lower() != '.json':
        raise PlanError('PLAN_OUTSIDE_ROOT_OR_BAD_TYPE')
    # TEAM_SYNC(Pipeline): require the job's own directory rather than a mutable
    # latest_*.json file. Avoid applying a new job to somebody else's plan.
    if path.parent.name != job_id:
        raise PlanError('PLAN_JOB_DIRECTORY_MISMATCH')
    try:
        if path.stat().st_size > max_bytes:
            raise PlanError('PLAN_TOO_LARGE')
        data = path.read_bytes()
    except OSError as exc:
        raise PlanError('PLAN_READ_FAILED') from exc
    if len(data) > max_bytes:
        raise PlanError('PLAN_TOO_LARGE')
    try:
        obj = json.loads(data.decode('utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PlanError('PLAN_BAD_JSON') from exc
    if not isinstance(obj, dict) or obj.get('schema_version') not in ('0.1', '0.2') or obj.get('job_id') != job_id:
        raise PlanError('PLAN_SCHEMA_OR_ID_MISMATCH')
    # v0.1 is read-only legacy compatibility for existing test/job plans;
    # v0.2 explicitly documents the image/paper frame. Never interpret these
    # millimetre coordinates directly as Doosan robot-base coordinates.
    if obj['schema_version'] == '0.2':
        if obj.get('unit') != 'mm' or obj.get('coordinate_frame') != 'paper_top_left_x_right_y_down':
            raise PlanError('PLAN_COORDINATE_FRAME_INVALID')
        grid = obj.get('grid')
        if grid is not None:
            if not isinstance(grid, dict) or grid.get('type') != '4x4':
                raise PlanError('PLAN_GRID_INVALID')
            cells = grid.get('cell_pen_ids')
            if not isinstance(cells, list) or len(cells) != 16 or any(p not in ('PEN_1', 'PEN_2', 'PEN_3') for p in cells):
                raise PlanError('PLAN_GRID_INVALID')
    paper = obj.get('paper_mm')
    if (not isinstance(paper, dict) or
            (paper.get('width'),paper.get('height')) not in ((210,297),(297,210))
            or obj['schema_version']=='0.1' and (paper.get('width'),paper.get('height')) != (210,297)):
        raise PlanError('PLAN_A4_PORTRAIT_REQUIRED')
    strokes = obj.get('strokes')
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 100_000:
        raise PlanError('PLAN_STROKES_INVALID')
    pens = []
    for expected, stroke in enumerate(strokes, 1):
        if not isinstance(stroke, dict) or type(stroke.get('stroke_id')) is not int or stroke['stroke_id'] != expected:
            raise PlanError('PLAN_STROKE_ORDER_INVALID')
        pen_id = stroke.get('pen_id')
        if not isinstance(pen_id, str) or not 1 <= len(pen_id) <= 64:
            raise PlanError('PLAN_PEN_ID_INVALID')
        if obj['schema_version'] == '0.2':
            if pen_id not in ('PEN_1', 'PEN_2', 'PEN_3'):
                raise PlanError('PLAN_PEN_ID_INVALID')
            if 'execution_order' in stroke and (type(stroke['execution_order']) is not int or stroke['execution_order'] != expected - 1):
                raise PlanError('PLAN_STROKE_ORDER_INVALID')
            if 'grid_id' in stroke:
                gid = stroke['grid_id']
                if grid is None or type(gid) is not int or not 0 <= gid < 16 or grid['cell_pen_ids'][gid] != pen_id:
                    raise PlanError('PLAN_GRID_INVALID')
        pens.append(pen_id)
        points = stroke.get('points_mm')
        if not isinstance(points, list) or len(points) < 2:
            raise PlanError('PLAN_POINTS_INVALID')
        for point in points:
            if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) for v in point):
                raise PlanError('PLAN_POINT_FORMAT_INVALID')
            x, y = point
            if not (math.isfinite(x) and math.isfinite(y) and 0 <= x <= paper['width'] and 0 <= y <= paper['height']):
                raise PlanError('PLAN_COORD_OUT_OF_A4')
    return PlanSummary(str(path), hashlib.sha256(data).hexdigest(), len(strokes), tuple(pens))
