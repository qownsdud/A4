"""4×4 퍼즐의 논리 펜 배정 및 획 단위 균형 배정."""
import math
import random

PENS = ('PEN_1', 'PEN_2', 'PEN_3')


def balanced_cells(seed=42, pen_ids=PENS):
    if tuple(pen_ids) != PENS:
        raise ValueError('PEN_1, PEN_2, PEN_3가 필요합니다.')
    cells = [pen_ids[0]] * 6 + [pen_ids[1]] * 5 + [pen_ids[2]] * 5
    random.Random(seed).shuffle(cells)
    return cells


def _stroke_length_and_midpoint(points):
    total = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    if total <= 0:
        return 0.0, (float(points[0][0]), float(points[0][1]))
    remaining = total / 2.0
    for a, b in zip(points, points[1:]):
        d = math.dist(a, b)
        if d >= remaining and d > 0:
            t = remaining / d
            return total, (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        remaining -= d
    return total, (float(points[-1][0]), float(points[-1][1]))


def split_long_stroke(points, max_length_mm=55.0):
    """길이가 임계값을 넘는 획을 약 max_length_mm 단위의 연속 구간으로 분할합니다."""
    if max_length_mm is None or max_length_mm <= 0 or len(points) < 2:
        return [points]
    total, _ = _stroke_length_and_midpoint(points)
    if total <= max_length_mm * 1.1:
        return [points]

    parts = max(2, math.ceil(total / max_length_mm))
    targets = [total * k / parts for k in range(1, parts)]
    target_idx = 0

    segments = []
    current = [list(points[0])]
    accumulated = 0.0

    for a, b in zip(points, points[1:]):
        seg_len = math.dist(a, b)
        if seg_len <= 0:
            continue
        seg_start = accumulated
        seg_end = accumulated + seg_len

        while target_idx < len(targets) and targets[target_idx] <= seg_end + 1e-9:
            ratio = min(1.0, max(0.0, (targets[target_idx] - seg_start) / seg_len))
            split_pt = [
                round(a[0] + ratio * (b[0] - a[0]), 3),
                round(a[1] + ratio * (b[1] - a[1]), 3),
            ]
            if current[-1] != split_pt:
                current.append(split_pt)
            if len(current) >= 2:
                segments.append(current)
            current = [list(split_pt)]
            target_idx += 1

        end_pt = [round(float(b[0]), 3), round(float(b[1]), 3)]
        if current[-1] != end_pt:
            current.append(end_pt)
        accumulated = seg_end

    if len(current) >= 2:
        segments.append(current)
    return segments or [points]


def assign_stroke_pens(strokes_points_mm, *, seed=42, pen_ids=PENS, neighbor_k=3, connected_pairs=None):
    """긴 획부터 연결 구간·근접 이웃 색 회피 + 누적 길이 균형으로 3가지 펜을 고르게 배정합니다."""
    if tuple(pen_ids) != PENS:
        raise ValueError('PEN_1, PEN_2, PEN_3가 필요합니다.')
    n = len(strokes_points_mm)
    if n == 0:
        return []

    linked = {i: set() for i in range(n)}
    for a, b in (connected_pairs or ()):
        if 0 <= a < n and 0 <= b < n and a != b:
            linked[a].add(b)
            linked[b].add(a)

    rng = random.Random(seed)
    pen_order = list(pen_ids)
    rng.shuffle(pen_order)

    metrics = [_stroke_length_and_midpoint(pts) for pts in strokes_points_mm]
    tie_breakers = [rng.random() for _ in range(n)]
    order = sorted(range(n), key=lambda i: (-metrics[i][0], tie_breakers[i]))

    assigned = [None] * n
    pen_totals = {p: 0.0 for p in pen_ids}
    placed = []  # (mx, my, pen_id)

    for idx in order:
        length, (mx, my) = metrics[idx]
        linked_pens = {assigned[j] for j in linked[idx] if assigned[j] is not None}
        if not placed:
            chosen = pen_order[0]
        else:
            dists = sorted(
                ((mx - px) ** 2 + (my - py) ** 2, p)
                for px, py, p in placed
            )
            closest_pen = dists[0][1]
            near_pens = [p for _, p in dists[:neighbor_k]]
            chosen = min(
                pen_order,
                key=lambda p: (
                    1 if p in linked_pens else 0,
                    1 if p == closest_pen else 0,
                    pen_totals[p],
                    near_pens.count(p),
                    pen_order.index(p),
                ),
            )
        assigned[idx] = chosen
        pen_totals[chosen] += length
        placed.append((mx, my, chosen))

    return assigned
