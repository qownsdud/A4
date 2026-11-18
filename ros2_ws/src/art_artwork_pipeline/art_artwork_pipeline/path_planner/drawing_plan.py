"""A4 DrawingPlan v0.2: pixel strokes -> paper-mm execution contract.

This is a *paper* coordinate frame, not a calibrated robot base frame.
No robot commands are issued by this module.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from ..puzzle.colors import balanced_cells
import re
import tempfile
import uuid
from pathlib import Path

PAPER = (210.0, 297.0)
PENS = ('PEN_1', 'PEN_2', 'PEN_3')
FRAME = 'paper_top_left_x_right_y_down'
_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')


def build_plan(strokes, width_px, height_px, *, job_id=None, seed=42,
               margin_mm=15.0, paper_size_mm=PAPER, pen_ids=PENS, artwork_box_mm=None):
    if not isinstance(width_px, int) or not isinstance(height_px, int) or min(width_px, height_px) < 2:
        raise ValueError('width_px and height_px must be integers >= 2')
    if tuple(pen_ids) != PENS:
        raise ValueError('v0.2 requires exactly PEN_1, PEN_2, PEN_3')
    pw, ph = map(float, paper_size_mm)
    if not math.isfinite(margin_mm) or margin_mm < 0 or not all(
            math.isfinite(v) and v > 2 * margin_mm for v in (pw, ph)):
        raise ValueError('invalid paper dimensions or margin')
    if (pw, ph) not in (PAPER,(297.,210.)):
        raise ValueError('v0.2 requires A4 210x297 or 297x210 mm')
    actual_id = job_id if job_id is not None else str(uuid.uuid4())
    if not isinstance(actual_id, str) or not _ID.fullmatch(actual_id):
        raise ValueError('invalid JobManager job_id')
    scale = min((pw - 2 * margin_mm) / (width_px - 1),
                (ph - 2 * margin_mm) / (height_px - 1))
    ox = (pw - (width_px - 1) * scale) / 2
    oy = (ph - (height_px - 1) * scale) / 2
    if artwork_box_mm is not None:
        left, top, width, height = map(float, artwork_box_mm)
        if (not all(math.isfinite(v) for v in (left, top, width, height))
                or min(left, top) < 0 or min(width, height) <= 0
                or left + width > pw or top + height > ph):
            raise ValueError('사진 배치 영역이 A4 범위를 벗어납니다.')
        scale = min(width / (width_px - 1), height / (height_px - 1))
        ox = left + (width - (width_px - 1) * scale) / 2
        oy = top + (height - (height_px - 1) * scale) / 2
    cells = balanced_cells(seed, pen_ids)
    paths = []
    for i, raw in enumerate(strokes):
        pts = raw.get('points', raw.get('points_px'))
        if not isinstance(pts, list) or len(pts) < 2:
            raise ValueError(f'stroke {i} must have at least 2 points')
        converted = []
        for pt in pts:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                raise ValueError(f'invalid point in stroke {i}')
            x, y = map(float, pt)
            if not (math.isfinite(x) and math.isfinite(y) and 0 <= x < width_px and 0 <= y < height_px):
                raise ValueError(f'out-of-image point in stroke {i}: {pt}')
            converted.append([round(ox + x * scale, 3), round(oy + y * scale, 3)])
        x0, y0 = converted[0]
        col = min(3, int(x0 / (pw / 4)))
        row = min(3, int(y0 / (ph / 4)))
        cell_id = row * 4 + col
        paths.append({'grid_id': cell_id, 'pen_id': cells[cell_id],
                      'layer': 'artwork', 'points_mm': converted})
    # Keep pen groups contiguous and the execution sequence unambiguous.
    paths.sort(key=lambda p: pen_ids.index(p['pen_id']))
    for order, path in enumerate(paths):
        path['stroke_id'] = order + 1
        path['execution_order'] = order
    plan = {'schema_version': '0.2', 'job_id': actual_id,
            'unit': 'mm', 'coordinate_frame': FRAME,
            'paper_mm': {'width': pw, 'height': ph}, 'seed': seed,
            'grid': {'type': '4x4', 'cell_pen_ids': cells}, 'strokes': paths}
    validate_plan(plan)
    return plan


def validate_plan(plan):
    """Validate Phase 3 v0.2 plans before preview and job-specific export."""
    if not isinstance(plan, dict) or plan.get('schema_version') != '0.2' or \
            plan.get('unit') != 'mm' or plan.get('coordinate_frame') != FRAME:
        raise ValueError('unsupported v0.2 plan contract')
    if not isinstance(plan.get('job_id'), str) or not _ID.fullmatch(plan['job_id']):
        raise ValueError('invalid job_id')
    if plan.get('paper_mm') not in ({'width':210.,'height':297.},{'width':297.,'height':210.}):
        raise ValueError('v0.2 requires A4 portrait or landscape')
    strokes = plan.get('strokes')
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 100_000:
        raise ValueError('invalid strokes')
    grid = plan.get('grid')
    cells = None
    if grid is not None:
        if not isinstance(grid, dict) or grid.get('type') != '4x4':
            raise ValueError('invalid grid')
        cells = grid.get('cell_pen_ids')
        if not isinstance(cells, list) or len(cells) != 16 or any(p not in PENS for p in cells):
            raise ValueError('invalid grid colors')
    for number, stroke in enumerate(strokes, 1):
        if not isinstance(stroke, dict) or type(stroke.get('stroke_id')) is not int or stroke['stroke_id'] != number:
            raise ValueError('invalid stroke_id sequence')
        if stroke.get('pen_id') not in PENS:
            raise ValueError('invalid pen_id')
        if 'execution_order' in stroke and (type(stroke['execution_order']) is not int or stroke['execution_order'] != number - 1):
            raise ValueError('invalid execution_order')
        if 'grid_id' in stroke:
            gid = stroke['grid_id']
            if type(gid) is not int or not 0 <= gid < 16 or cells is None or cells[gid] != stroke['pen_id']:
                raise ValueError('grid and pen mismatch')
        points = stroke.get('points_mm')
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError('invalid points_mm')
        for point in points:
            if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) for v in point):
                raise ValueError('invalid point format')
            x, y = point
            if not (math.isfinite(x) and math.isfinite(y) and 0 <= x <= plan['paper_mm']['width'] and 0 <= y <= plan['paper_mm']['height']):
                raise ValueError('point outside A4')
    return True


def write_job_plan(plan, plan_root):
    """Atomically publish a single immutable JobManager plan; never overwrite.

    The root must be a trusted local workspace path. This does not authorize
    sending the plan to a real robot; calibration is the controller's job.
    """
    validate_plan(plan)
    root = Path(plan_root).expanduser().resolve()
    job_id = plan['job_id']
    directory = root / job_id
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve().parent != root:
        raise ValueError('job directory escapes ART_JOB_PLAN_ROOT')
    target = directory / 'drawing_plan.json'
    payload = (json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if len(payload) > 5_000_000:
        raise ValueError('DrawingPlan exceeds JobManager 5 MB limit')
    fd, staged = tempfile.mkstemp(prefix='.drawing_plan_', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and fails if the destination exists.
        # Unlike os.replace(), it cannot overwrite an approved job plan.
        os.link(staged, target)
    finally:
        os.unlink(staged)
    return target.resolve()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--strokes', type=Path, required=True)
    p.add_argument('--image-width', type=int, required=True)
    p.add_argument('--image-height', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--job-id', default=None)
    p.add_argument('--plan-root', type=Path, default=None)
    p.add_argument('--seed', type=int, default=42)
    a = p.parse_args()
    data = json.loads(a.strokes.read_text(encoding='utf-8'))
    plan = build_plan(data, a.image_width, a.image_height, seed=a.seed, job_id=a.job_id)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"Created {a.output} for job {plan['job_id']}")
    if a.plan_root:
        print('Published', write_job_plan(plan, a.plan_root))


if __name__ == '__main__':
    main()
