"""Optimize an A4 DrawingPlan, never interleaving logical pen groups.

The optional vpype backend executes linemerge, linesimplify and linesort
within each pen layer. The OpenCV fallback provides the same three stages.
Coordinates in this module are millimetres; no robot commands are issued.
"""
from __future__ import annotations

from copy import deepcopy
import math
import random

import cv2
import numpy as np

PENS = ('PEN_1', 'PEN_2', 'PEN_3')


from ..puzzle.colors import balanced_cells


def path_length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def stroke_midpoint(points):
    """Arc-length midpoint, not merely point-array midpoint."""
    remaining = path_length(points) / 2
    for a, b in zip(points, points[1:]):
        d = math.dist(a, b)
        if d >= remaining and d > 0:
            t = remaining / d
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        remaining -= d
    return tuple(points[-1])


def cell_index(point, paper):
    w, h = paper
    return min(3, max(0, int(point[1] * 4 / h))) * 4 + min(3, max(0, int(point[0] * 4 / w)))


def nearest_color_cell(points, paper, cells, pen):
    """Reconstruct a representative grid_id after same-pen merge."""
    x, y = stroke_midpoint(points)
    w, h = paper
    candidates = [i for i, color in enumerate(cells) if color == pen]
    return min(candidates, key=lambda i: ((i % 4 + 0.5) * w / 4 - x) ** 2 +
               ((i // 4 + 0.5) * h / 4 - y) ** 2)


def simplify_points(points, tolerance):
    pts = np.asarray(points, dtype=np.float32)
    is_closed = len(pts) > 3 and np.linalg.norm(pts[0] - pts[-1]) < 1e-4
    approx = cv2.approxPolyDP(pts.reshape(-1, 1, 2), tolerance, closed=is_closed)
    coords = [[float(x), float(y)] for x, y in approx.reshape(-1, 2)]
    if is_closed and len(coords) >= 3:
        coords.append(coords[0][:])
    if not is_closed and len(coords) < 2:
        return [list(points[0]), list(points[-1])]
    return coords


def _merge_same_pen(lines, tolerance):
    remaining = [list(map(list, line)) for line in lines]
    result = []
    while remaining:
        line = remaining.pop(0)
        while remaining:
            if len(line) > 2 and math.dist(line[0], line[-1]) <= tolerance:
                break
            candidates = []
            for i, other in enumerate(remaining):
                if len(other) > 2 and math.dist(other[0], other[-1]) <= tolerance:
                    continue
                for mode, a, b in [(0, line[-1], other[0]), (1, line[-1], other[-1]),
                                   (2, line[0], other[-1]), (3, line[0], other[0])]:
                    d = math.dist(a, b)
                    if d <= tolerance:
                        candidates.append((d, i, mode))
            if not candidates:
                break
            _, i, mode = min(candidates)
            other = remaining.pop(i)
            if mode == 0:
                line += other[1:] if line[-1] == other[0] else other
            elif mode == 1:
                other.reverse()
                line += other[1:] if line[-1] == other[0] else other
            elif mode == 2:
                line = (other[:-1] if other[-1] == line[0] else other) + line
            else:
                other.reverse()
                line = (other[:-1] if other[-1] == line[0] else other) + line
        result.append(line)
    return result


def _sort_same_pen(lines):
    remaining = [list(s) for s in lines]
    ordered = []
    previous = (0.0, 0.0)
    while remaining:
        best = min((math.dist(previous, s[0]), i, False) for i, s in enumerate(remaining))
        backwards = min((math.dist(previous, s[-1]), i, True) for i, s in enumerate(remaining))
        dist, i, reverse = min(best, backwards)
        chosen = remaining.pop(i)
        if reverse:
            chosen.reverse()
        ordered.append(chosen)
        previous = chosen[-1]
    return ordered



def _smooth_curve(points, step_mm):
    """Resample a polyline into a PCHIP smooth path without new pen lifts."""
    if len(points) < 3:
        return points
    try:
        from scipy.interpolate import PchipInterpolator
    except ImportError:
        return points
    coords = np.asarray(points, dtype=float)
    lengths = np.linalg.norm(np.diff(coords, axis=0), axis=1)
    keep = np.r_[True, lengths > 1e-6]
    coords = coords[keep]
    if len(coords) < 3:
        return coords.tolist()
    arclength = np.r_[0, np.cumsum(np.linalg.norm(np.diff(coords, axis=0), axis=1))]
    sample_count = min(2500, max(len(coords), int(arclength[-1] / step_mm) + 1))
    t = np.linspace(0, arclength[-1], sample_count)
    x = PchipInterpolator(arclength, coords[:, 0])(t)
    y = PchipInterpolator(arclength, coords[:, 1])(t)
    return [[round(float(a), 3), round(float(b), 3)] for a, b in zip(x, y)]

def _clean_dwell_points(points, min_step_mm=0.85):
    """잉크 번짐 방지를 위해 지나치게 가까운 연속 점(< min_step_mm)을 병합합니다."""
    if len(points) <= 2 or min_step_mm <= 0:
        return [list(p) for p in points]
    is_closed = math.dist(points[0], points[-1]) < 1e-4
    cleaned = [list(points[0])]
    for pt in points[1:-1]:
        if math.dist(cleaned[-1], pt) >= min_step_mm:
            cleaned.append(list(pt))
    end_pt = list(points[-1])
    if is_closed:
        if len(cleaned) > 2 and math.dist(cleaned[-1], end_pt) < min_step_mm * 0.5:
            cleaned.pop()
        cleaned.append(end_pt)
    else:
        if len(cleaned) >= 2 and math.dist(cleaned[-1], end_pt) < min_step_mm * 0.5:
            cleaned[-1] = end_pt
        elif math.dist(cleaned[-1], end_pt) > 1e-6:
            cleaned.append(end_pt)
    if len(cleaned) < 2:
        return [list(points[0]), list(points[-1])]
    return cleaned


def _sample_polyline(points, step_mm=0.5):
    """폴리라인을 step_mm 간격 이하의 점열로 샘플링합니다."""
    if len(points) < 2:
        return [list(p) for p in points]
    samples = [list(points[0])]
    for a, b in zip(points, points[1:]):
        dist = math.dist(a, b)
        if dist <= 1e-6:
            continue
        steps = max(1, int(math.ceil(dist / step_mm)))
        for k in range(1, steps + 1):
            t = k / steps
            samples.append([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t])
    return samples


def _limit_ink_overdraw(
    paths,
    paper,
    *,
    max_passes=1,
    cell_mm=0.5,
    patch_mm=3.0,
    max_local_ink_mm=6.5,
    min_stroke_mm=2.5,
    allow_cross_mm=1.8,
    simplify_tolerance_mm=0.22,
    min_point_spacing_mm=0.85,
):
    """같은 점/인접 영역에 과도한 중복 펜질이 누적되지 않도록 선분을 정리합니다.

    - max_passes=1: 이미 그려진 선(1회)을 따라 나란히 덧그리는 구간은 제거하되,
      직교 교차(<= allow_cross_mm, 누적 패스 <= max_passes)는 끊김 없이 1회 통과(총 2회)만 허용합니다.
    - 3회 이상 겹치거나 국소 3x3mm 영역에 잉크 밀도(max_local_ink_mm)가 초과된 구간은 차단합니다.
    """
    if not paths:
        return []
    pw, ph = float(paper[0]), float(paper[1])
    gw = int(math.ceil(pw / cell_mm)) + 3
    gh = int(math.ceil(ph / cell_mm)) + 3
    dw = int(math.ceil(pw / patch_mm)) + 3
    dh = int(math.ceil(ph / patch_mm)) + 3
    ink_passes = np.zeros((gh, gw), dtype=np.uint16)
    ink_density = np.zeros((dh, dw), dtype=np.float32)

    # 주요 윤곽(긴 획)을 우선 보존하고, 겹치는 짧은 잔선을 뒤에서 정리합니다.
    order = sorted(range(len(paths)), key=lambda i: (-path_length(paths[i]['points_mm']), i))
    kept = []
    step_mm = cell_mm
    grace_samples = max(4, int(round(3.0 / step_mm)))

    for idx in order:
        item = paths[idx]
        if item.get('layer', 'artwork') != 'artwork':
            kept.append(item)
            continue
        pts = item['points_mm']
        if path_length(pts) < min_stroke_mm:
            continue

        samples = _sample_polyline(pts, step_mm=step_mm)
        if len(samples) < 2:
            continue
        is_closed_loop = len(samples) > grace_samples * 2 and math.dist(samples[0], samples[-1]) <= 1.5

        blocked = [False] * len(samples)
        hard_blocked = [False] * len(samples)
        self_cells: set[tuple[int, int]] = set()
        recent_queue: list[tuple[int, int]] = []

        for i, (x, y) in enumerate(samples):
            cx = max(0, min(gw - 1, int(x / cell_mm)))
            cy = max(0, min(gh - 1, int(y / cell_mm)))
            bx = max(0, min(dw - 1, int(x / patch_mm)))
            by = max(0, min(dh - 1, int(y / patch_mm)))

            near_loop_close = is_closed_loop and i >= len(samples) - grace_samples
            self_hit = (not near_loop_close) and ((cx, cy) in self_cells)
            passes_here = int(ink_passes[cy, cx])
            over_pass = max_passes is not None and passes_here >= max_passes
            over_hard = max_passes is not None and passes_here >= (max_passes + 1)
            over_dense = max_local_ink_mm is not None and float(ink_density[by, bx]) >= max_local_ink_mm
            blocked[i] = self_hit or over_pass or over_dense
            hard_blocked[i] = self_hit or over_hard or over_dense

            recent_queue.append((cx, cy))
            if len(recent_queue) > grace_samples:
                ox, oy = recent_queue.pop(0)
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = ox + dx, oy + dy
                        if 0 <= nx < gw and 0 <= ny < gh:
                            self_cells.add((nx, ny))

        # 이미 1회 그려진 선과의 짧은 직교 교차(<= allow_cross_mm)만 연속 통과(총 2회) 허용
        # 2회 이상 겹쳤거나(hard_blocked) 밀도 초과 구간은 절대 브리지하지 않음
        max_bridge_samples = max(1, int(round(allow_cross_mm / step_mm)))
        i = 0
        n = len(blocked)
        while i < n:
            if not blocked[i]:
                i += 1
                continue
            j = i
            while j < n and blocked[j]:
                j += 1
            if (
                i > 0
                and j < n
                and (j - i) <= max_bridge_samples
                and not any(hard_blocked[k] for k in range(i, j))
            ):
                for k in range(i, j):
                    blocked[k] = False
            i = j

        # 허용 구간만 서브 획으로 추출
        sub_runs = []
        i = 0
        while i < n:
            if blocked[i]:
                i += 1
                continue
            j = i
            while j < n and not blocked[j]:
                j += 1
            if j - i >= 2:
                sub_runs.append(samples[i:j])
            i = j

        for run in sub_runs:
            if path_length(run) < min_stroke_mm:
                continue
            tol = max(0.18, float(simplify_tolerance_mm))
            cleaned = simplify_points(run, tol)
            cleaned = _clean_dwell_points(cleaned, min_step_mm=min_point_spacing_mm)
            if len(cleaned) < 2 or path_length(cleaned) < min_stroke_mm:
                continue
            cleaned = [
                [round(max(0.0, min(pw, float(x))), 3), round(max(0.0, min(ph, float(y))), 3)]
                for x, y in cleaned
            ]

            # 확정된 서브 획의 잉크 발자국을 기록 (서브 획당 셀 최대 +1)
            touched: set[tuple[int, int]] = set()
            for a, b in zip(run, run[1:]):
                seg_len = math.dist(a, b)
                mx, my = 0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1])
                bx = max(0, min(dw - 1, int(mx / patch_mm)))
                by = max(0, min(dh - 1, int(my / patch_mm)))
                ink_density[by, bx] += seg_len
                cx = max(0, min(gw - 1, int(mx / cell_mm)))
                cy = max(0, min(gh - 1, int(my / cell_mm)))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < gw and 0 <= ny < gh:
                            touched.add((nx, ny))
            for cx, cy in touched:
                ink_passes[cy, cx] += 1

            kept.append(dict(item, points_mm=cleaned))

    if not kept and paths:
        kept.append(paths[order[0]])
    return kept


def optimize_plan(plan, *, merge_tolerance_mm=0.35, simplify_tolerance_mm=0.25,
                  backend='auto', seed=None, max_strokes=None, curve_step_mm=1.0,
                  min_point_spacing_mm=0.85, min_stroke_mm=2.5,
                  max_ink_passes=1, max_local_ink_mm=6.5):
    """Merge/simplify/sort paths within pen groups; retain continuous paths.

    backend: 'auto' uses vpype if installed, otherwise OpenCV fallback.
    'vpype' requires vpype installed; 'opencv' forces pure OpenCV fallback.
    """
    if not 0 <= merge_tolerance_mm <= 1.0 or not 0 <= simplify_tolerance_mm <= 2.0:
        raise ValueError('tolerance out of safe range')
    if max_strokes is not None and max_strokes < 1:
        raise ValueError('max_strokes must be positive or None')
    if curve_step_mm < 0:
        raise ValueError('curve_step_mm must be nonnegative')
    if backend not in ('auto', 'vpype', 'opencv'):
        raise ValueError('invalid backend')
    out = deepcopy(plan)
    pens = PENS
    seed = plan.get('seed', 42) if seed is None else seed
    cells = plan.get('grid', {}).get('cell_pen_ids') or balanced_cells(seed, pens)
    out['grid'] = {'type': '4x4', 'cell_pen_ids': list(cells)}
    paper = (out['paper_mm']['width'], out['paper_mm']['height'])
    grouped = {}
    for path in plan['strokes']:
        pts = path['points_mm']
        pen = path.get('pen_id', cells[cell_index(stroke_midpoint(pts), paper)])
        layer = path.get('layer', 'artwork')
        grouped.setdefault((pen, layer), []).append(pts)

    vpype_backend = backend in ('auto', 'vpype')
    if vpype_backend:
        try:
            import vpype
            import vpype_cli
        except ImportError:
            if backend == 'vpype':
                raise ImportError('vpype backend requested: pip install vpype')
            vpype_backend = False

    new_paths = []
    for pen, layer in sorted(grouped, key=lambda key: (pens.index(key[0]), key[1])):
        lines = grouped[(pen, layer)]
        if not lines:
            continue
        if vpype_backend:
            doc = vpype.Document()
            doc.add([np.asarray([complex(x, y) for x, y in line]) for line in lines], layer_id=1)
            # Numeric CLI tolerances are in document coordinate units (our mm).
            pipeline = (f'linemerge --tolerance {merge_tolerance_mm} '
                        f'linesimplify --tolerance {simplify_tolerance_mm} linesort')
            processed = vpype_cli.execute(pipeline, document=doc)
            optimized = [[[float(z.real), float(z.imag)] for z in line]
                         for line in processed.layers[1]]
        else:
            joined = _merge_same_pen(lines, merge_tolerance_mm)
            simplified = [simplify_points(line, simplify_tolerance_mm) for line in joined]
            optimized = _sort_same_pen(simplified)
        for points in optimized:
            if layer == 'artwork' and min_point_spacing_mm > 0:
                points = _clean_dwell_points(points, min_step_mm=min_point_spacing_mm)
            if len(points) < 2 or path_length(points) < 1e-8:
                continue
            points = [[round(float(x), 3), round(float(y), 3)] for x, y in points]
            new_paths.append({
                'stroke_id': len(new_paths) + 1,
                'grid_id': nearest_color_cell(points, paper, cells, pen),
                'pen_id': pen, 'layer': layer, 'points_mm': points,
                'execution_order': len(new_paths), 'continuous_pen_down': True,
            })
    if (max_ink_passes is not None or max_local_ink_mm is not None) and any(
            p.get('layer', 'artwork') == 'artwork' for p in new_paths):
        pruned = _limit_ink_overdraw(
            new_paths,
            paper,
            max_passes=max_ink_passes,
            max_local_ink_mm=max_local_ink_mm,
            min_stroke_mm=min_stroke_mm,
            simplify_tolerance_mm=simplify_tolerance_mm,
            min_point_spacing_mm=min_point_spacing_mm,
        )
        # 잉크 중복 정리 후에도 펜별 그룹 순서와 최단 공중 이동 순서를 유지합니다.
        regrouped = {}
        for item in pruned:
            regrouped.setdefault((item['pen_id'], item['layer']), []).append(item)
        reordered = []
        for pen, layer in sorted(regrouped, key=lambda key: (pens.index(key[0]) if key[0] in pens else len(pens), key[1])):
            items = regrouped[(pen, layer)]
            if layer == 'artwork':
                sorted_lines = _sort_same_pen([p['points_mm'] for p in items])
                for points in sorted_lines:
                    reordered.append({
                        'stroke_id': len(reordered) + 1,
                        'grid_id': nearest_color_cell(points, paper, cells, pen),
                        'pen_id': pen,
                        'layer': layer,
                        'points_mm': points,
                        'execution_order': len(reordered),
                        'continuous_pen_down': True,
                    })
            else:
                reordered.extend(items)
        new_paths = reordered
    if max_strokes is not None and len(new_paths) > max_strokes and all(p['layer'] == 'artwork' for p in new_paths):
        # Preserve a few distinctive details in each spatial region before
        # filling remaining slots with the longest contours.
        priority = sorted(range(len(new_paths)),
                          key=lambda i: (-path_length(new_paths[i]['points_mm']), i))
        reserved = []
        seen = set()
        for i in priority:
            k = new_paths[i]['grid_id']
            if k not in seen and len(reserved) < max_strokes:
                reserved.append(i)
                seen.add(k)
        chosen = set((reserved + [i for i in priority if i not in reserved])[:max_strokes])
        new_paths = [p for i, p in enumerate(new_paths) if i in chosen]
        # Re-sort after pruning to retain a short pen-up route in each pen group.
        arranged = []
        for pen in pens:
            source = [p for p in new_paths if p['pen_id'] == pen]
            if not source:
                continue
            sorted_lines = _sort_same_pen([p['points_mm'] for p in source])
            for points in sorted_lines:
                arranged.append(dict(source[0], points_mm=points,
                    grid_id=nearest_color_cell(points, paper, cells, pen)))
        new_paths = arranged
    if curve_step_mm > 0:
        new_paths = [dict(p, points_mm=_smooth_curve(p['points_mm'], curve_step_mm))
                     for p in new_paths]
    for i, p in enumerate(new_paths):
        p['stroke_id'] = i + 1
        p['execution_order'] = i
    out['strokes'] = new_paths
    out['optimization'] = {'backend': 'vpype' if vpype_backend else 'opencv',
                           'merge_tolerance_mm': merge_tolerance_mm,
                           'simplify_tolerance_mm': simplify_tolerance_mm,
                           'input_strokes': len(plan['strokes']),
                           'output_strokes': len(new_paths),
                           'pen_order': list(pens),
                           'max_strokes': max_strokes,
                           'curve_step_mm': curve_step_mm}
    return out
