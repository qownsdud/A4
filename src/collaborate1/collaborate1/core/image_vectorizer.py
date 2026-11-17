"""라인아트 PNG 이미지를 로봇 드로잉용 벡터 경로(JSON / SVG)로 변환하는 모듈."""

import json
import math
import os
from typing import Dict, List, Set, Tuple

import cv2
import numpy as np

Point2D = Tuple[float, float]


def zhang_suen_thinning(binary_img: np.ndarray) -> np.ndarray:
    """이진 이미지(0/1)를 1픽셀 두께 중심선(Skeleton)으로 세선화한다."""
    img = (binary_img > 0).astype(np.uint8)
    while True:
        changed = False
        for step in (0, 1):
            p2 = img[:-2, 1:-1]
            p3 = img[:-2, 2:]
            p4 = img[1:-1, 2:]
            p5 = img[2:, 2:]
            p6 = img[2:, 1:-1]
            p7 = img[2:, :-2]
            p8 = img[1:-1, :-2]
            p9 = img[:-2, :-2]
            p1 = img[1:-1, 1:-1]

            neighbors = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            transitions = (
                ((p2 == 0) & (p3 == 1)).astype(np.uint8)
                + ((p3 == 0) & (p4 == 1)).astype(np.uint8)
                + ((p4 == 0) & (p5 == 1)).astype(np.uint8)
                + ((p5 == 0) & (p6 == 1)).astype(np.uint8)
                + ((p6 == 0) & (p7 == 1)).astype(np.uint8)
                + ((p7 == 0) & (p8 == 1)).astype(np.uint8)
                + ((p8 == 0) & (p9 == 1)).astype(np.uint8)
                + ((p9 == 0) & (p2 == 1)).astype(np.uint8)
            )

            cond_base = (p1 == 1) & (neighbors >= 2) & (neighbors <= 6) & (transitions == 1)
            if step == 0:
                cond_step = ((p2 * p4 * p6) == 0) & ((p4 * p6 * p8) == 0)
            else:
                cond_step = ((p2 * p4 * p8) == 0) & ((p2 * p6 * p8) == 0)

            mask = cond_base & cond_step
            if np.any(mask):
                img[1:-1, 1:-1][mask] = 0
                changed = True
        if not changed:
            break
    return img


def _build_adj(skel: np.ndarray) -> Dict[Tuple[int, int], List[Tuple[int, int]]]:
    h, w = skel.shape
    ys, xs = np.where(skel > 0)
    fg = set(zip(xs.tolist(), ys.tolist()))
    offsets = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]
    adj: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for x, y in fg:
        adj[(x, y)] = [(x + dx, y + dy) for dx, dy in offsets if 0 <= x + dx < w and 0 <= y + dy < h and (x + dx, y + dy) in fg]
    return adj


def prune_spurs(skel: np.ndarray, max_spur_len: int = 3) -> np.ndarray:
    """세선화 과정에서 분기점에 생긴 짧은 잔가지(spur)를 제거해 주선만 매끄럽게 남긴다."""
    out = skel.copy()
    adj = _build_adj(out)
    endpoints = [pt for pt, nbrs in adj.items() if len(nbrs) == 1]

    to_remove: Set[Tuple[int, int]] = set()
    for ep in endpoints:
        branch = [ep]
        prev = None
        curr = ep
        hit_junction = False
        for _ in range(max_spur_len):
            nbrs = [n for n in adj[curr] if n != prev]
            if not nbrs:
                break
            nxt = nbrs[0]
            if len(adj[nxt]) >= 3:
                hit_junction = True
                break
            if len(adj[nxt]) == 1:
                break
            branch.append(nxt)
            prev, curr = curr, nxt
        if hit_junction and len(branch) <= max_spur_len:
            to_remove.update(branch)

    for x, y in to_remove:
        out[y, x] = 0
    return out


def trace_skeleton_strokes(skel: np.ndarray) -> List[List[Tuple[int, int]]]:
    """1px 스켈레톤에서 분기점에서도 직진성을 유지하며 긴 연속 획을 추출한다."""
    adj = _build_adj(skel)
    if not adj:
        return []

    visited_edges: Set[Tuple[Tuple[int, int], Tuple[int, int]]] = set()
    strokes: List[List[Tuple[int, int]]] = []

    def edge_key(a: Tuple[int, int], b: Tuple[int, int]) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        return (a, b) if a <= b else (b, a)

    def walk_from(start: Tuple[int, int]) -> None:
        for nxt in adj[start]:
            ek = edge_key(start, nxt)
            if ek in visited_edges:
                continue
            stroke = [start, nxt]
            visited_edges.add(ek)
            prev, curr = start, nxt
            while True:
                candidates = [
                    n for n in adj[curr]
                    if n != prev and edge_key(curr, n) not in visited_edges
                ]
                if not candidates:
                    break
                if len(candidates) > 1:
                    # 최근 3픽셀 진행 벡터 기준 가장 부드럽게 이어지는 방향 선택
                    ref = stroke[-4] if len(stroke) >= 4 else stroke[0]
                    vx, vy = curr[0] - ref[0], curr[1] - ref[1]
                    candidates.sort(
                        key=lambda n: (n[0] - curr[0]) * vx + (n[1] - curr[1]) * vy,
                        reverse=True,
                    )
                chosen = candidates[0]
                visited_edges.add(edge_key(curr, chosen))
                stroke.append(chosen)
                prev, curr = curr, chosen
            strokes.append(stroke)

    # 끝점(차수==1)부터 시작해 가장 긴 본선 우선 추적
    for pt, nbrs in adj.items():
        if len(nbrs) == 1:
            walk_from(pt)
    for pt, nbrs in adj.items():
        if len(nbrs) != 2:
            walk_from(pt)
    for pt in adj:
        walk_from(pt)

    return strokes


def chaikin_smooth(pts: List[Point2D], iterations: int = 1) -> List[Point2D]:
    """Chaikin 코너 절단 스무딩으로 픽셀 계단 현상을 부드러운 곡선으로 다듬는다."""
    cur = list(pts)
    for _ in range(iterations):
        if len(cur) < 3:
            break
        nxt: List[Point2D] = [cur[0]]
        for i in range(len(cur) - 1):
            p0, p1 = cur[i], cur[i + 1]
            nxt.append((0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]))
            nxt.append((0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]))
        nxt.append(cur[-1])
        cur = nxt
    return cur


def simplify_and_sort_strokes(
    strokes: List[List[Tuple[int, int]]],
    epsilon_px: float = 0.8,
    min_len_px: float = 2.0,
    merge_dist_px: float = 4.0,
) -> List[List[Point2D]]:
    """스무딩, RDP 단순화, 이동 최소화 정렬 및 근접 끝점 병합을 수행한다."""
    cleaned: List[List[Point2D]] = []
    for st in strokes:
        if len(st) < 2:
            continue
        length = sum(math.hypot(st[i + 1][0] - st[i][0], st[i + 1][1] - st[i][1]) for i in range(len(st) - 1))
        if length < min_len_px:
            continue
        smoothed = chaikin_smooth([(float(x), float(y)) for x, y in st], iterations=1)
        arr = np.array(smoothed, dtype=np.float32).reshape(-1, 1, 2)
        approx = cv2.approxPolyDP(arr, epsilon_px, closed=False).reshape(-1, 2)
        if len(approx) >= 2:
            cleaned.append([(float(x), float(y)) for x, y in approx])

    if not cleaned:
        return []

    ordered: List[List[Point2D]] = []
    remaining = list(cleaned)
    ordered.append(remaining.pop(0))

    while remaining:
        ex, ey = ordered[-1][-1]
        best_idx = 0
        best_rev = False
        best_dist = float("inf")
        for idx, cand in enumerate(remaining):
            d_start = math.hypot(cand[0][0] - ex, cand[0][1] - ey)
            d_end = math.hypot(cand[-1][0] - ex, cand[-1][1] - ey)
            if d_start < best_dist:
                best_dist = d_start
                best_idx = idx
                best_rev = False
            if d_end < best_dist:
                best_dist = d_end
                best_idx = idx
                best_rev = True
        nxt = remaining.pop(best_idx)
        if best_rev:
            nxt = list(reversed(nxt))
        if best_dist <= merge_dist_px:
            ordered[-1].extend(nxt[1:] if best_dist < 1e-3 else nxt)
        else:
            ordered.append(nxt)

    return ordered


def vectorize_png(
    png_path: str,
    target_max_mm: float = 120.0,
    threshold: int = 180,
    epsilon_px: float = 0.8,
    min_len_px: float = 2.0,
) -> Dict[str, object]:
    """PNG 라인아트 이미지를 벡터화하여 JSON, SVG, 미리보기 PNG를 생성한다."""
    gray = cv2.imread(png_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(f"이미지를 읽을 수 없습니다: {png_path}")

    h, w = gray.shape
    binary = (gray < threshold).astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    skel = zhang_suen_thinning(binary)
    skel = prune_spurs(skel, max_spur_len=3)
    raw_strokes = trace_skeleton_strokes(skel)
    strokes_px = simplify_and_sort_strokes(raw_strokes, epsilon_px=epsilon_px, min_len_px=min_len_px)

    scale = target_max_mm / max(w, h)
    cx_px, cy_px = w / 2.0, h / 2.0
    strokes_mm = [
        [(round((x - cx_px) * scale, 3), round((cy_px - y) * scale, 3)) for x, y in st]
        for st in strokes_px
    ]

    stem, _ = os.path.splitext(png_path)
    json_path = f"{stem}_strokes.json"
    svg_path = f"{stem}.svg"
    preview_path = f"{stem}_preview.png"

    payload = {
        "source": png_path,
        "image_size_px": [w, h],
        "target_max_mm": target_max_mm,
        "num_strokes": len(strokes_mm),
        "num_points": sum(len(s) for s in strokes_mm),
        "strokes_mm": strokes_mm,
        "strokes_px": [[(round(x, 2), round(y, 2)) for x, y in st] for st in strokes_px],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
        '<g fill="none" stroke="black" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">',
    ]
    for st in strokes_px:
        pts_str = " ".join(f"{x:.2f},{y:.2f}" for x, y in st)
        svg_lines.append(f'  <polyline points="{pts_str}" />')
    svg_lines.append("</g></svg>")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg_lines))

    preview = np.full((h, w, 3), 255, dtype=np.uint8)
    for st in strokes_px:
        pts_np = np.array(st, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(preview, [pts_np], isClosed=False, color=(0, 0, 0), thickness=2, lineType=cv2.LINE_AA)
    cv2.imwrite(preview_path, preview)

    return {
        "json_path": json_path,
        "svg_path": svg_path,
        "preview_path": preview_path,
        "num_strokes": len(strokes_mm),
        "num_points": payload["num_points"],
    }
