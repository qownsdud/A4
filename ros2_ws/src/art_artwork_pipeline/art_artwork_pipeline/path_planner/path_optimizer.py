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

def optimize_plan(plan, *, merge_tolerance_mm=0.35, simplify_tolerance_mm=0.25,
                  backend='auto', seed=None, max_strokes=None, curve_step_mm=1.0):
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
            if len(points) < 2 or path_length(points) < 1e-8:
                continue
            points = [[round(float(x), 3), round(float(y), 3)] for x, y in points]
            new_paths.append({
                'stroke_id': len(new_paths) + 1,
                'grid_id': nearest_color_cell(points, paper, cells, pen),
                'pen_id': pen, 'layer': layer, 'points_mm': points,
                'execution_order': len(new_paths), 'continuous_pen_down': True,
            })
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
