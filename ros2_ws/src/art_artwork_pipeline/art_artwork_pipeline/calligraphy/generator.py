"""한글·영문·숫자·특수문자를 왼쪽부터 순서대로 폰트 스켈레톤 기반 종이 mm 경로로 변환합니다."""

from __future__ import annotations

from functools import lru_cache
import math
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
from fontTools.ttLib import TTFont
import numpy as np
from PIL import Image, ImageDraw, ImageFont

_DEFAULT_FONT_CANDIDATES = (
    str(Path.home() / ".local/share/fonts/NanumBrush.ttf"),
    "/usr/share/fonts/truetype/nanum/NanumBrush.ttf",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/nanum/NanumMyeongjoBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumSquareB.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSymbols-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

_RENDER_SIZE = 140
_PADDING = 20
_MIN_DOT_MASK_AREA = 15
MIN_THICKNESS_Z_DELTA_MM = 0.7   # 가장 얇은 구간: 기준 높이보다 +0.7mm 상승
MAX_THICKNESS_Z_DELTA_MM = -1.3  # 가장 두꺼운 구간: 기준 높이보다 -1.3mm 하강
_MAX_THICKNESS_SAMPLE_SEG_PX = 8.0


def _font_candidates() -> Tuple[str, ...]:
    env_font = os.environ.get("ART_CALLIGRAPHY_FONT", "").strip()
    candidates = ([env_font] if env_font else []) + list(_DEFAULT_FONT_CANDIDATES)
    return tuple(p for p in candidates if p and Path(p).is_file())


@lru_cache(maxsize=32)
def _load_cmap(font_path: str) -> set[int]:
    try:
        with TTFont(font_path, fontNumber=0) as tt:
            cmap = tt.getBestCmap()
            return set(cmap.keys()) if cmap else set()
    except Exception:
        return set()


@lru_cache(maxsize=32)
def _load_pil_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path, size)


def _select_font_for_char(ch: str, candidates: Tuple[str, ...]) -> Optional[str]:
    code = ord(ch)
    for path in candidates:
        if code in _load_cmap(path):
            return path
    return None


def _zhang_suen_thinning(binary: np.ndarray) -> np.ndarray:
    """이진 마스크(0/1)를 1픽셀 두께 중심선으로 세선화합니다."""
    img = (binary > 0).astype(np.uint8)
    if img.shape[0] < 3 or img.shape[1] < 3:
        return img
    while True:
        changed = False
        for step in (0, 1):
            p2, p3, p4 = img[:-2, 1:-1], img[:-2, 2:], img[1:-1, 2:]
            p5, p6, p7 = img[2:, 2:], img[2:, 1:-1], img[2:, :-2]
            p8, p9, p1 = img[1:-1, :-2], img[:-2, :-2], img[1:-1, 1:-1]

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
            cond = (p1 == 1) & (neighbors >= 2) & (neighbors <= 6) & (transitions == 1)
            if step == 0:
                cond &= ((p2 * p4 * p6) == 0) & ((p4 * p6 * p8) == 0)
            else:
                cond &= ((p2 * p4 * p8) == 0) & ((p2 * p6 * p8) == 0)

            if np.any(cond):
                img[1:-1, 1:-1][cond] = 0
                changed = True
        if not changed:
            break
    return img


def _prune_spurs(skel: np.ndarray, max_spur_len: int = 3) -> np.ndarray:
    """세선화 분기점의 짧은 잔가지를 제거해 곡선/원 주변의 불필요한 점·가지 찍힘을 막습니다."""
    if max_spur_len <= 0:
        return skel
    out = skel.copy()
    h, w = out.shape
    offsets = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]
    for _ in range(max_spur_len):
        ys, xs = np.where(out > 0)
        to_remove: List[Tuple[int, int]] = []
        for y, x in zip(ys.tolist(), xs.tolist()):
            nbs = [
                (x + dx, y + dy)
                for dx, dy in offsets
                if 0 <= x + dx < w and 0 <= y + dy < h and out[y + dy, x + dx] > 0
            ]
            if len(nbs) == 1:
                nx, ny = nbs[0]
                ndeg = sum(
                    1
                    for ddx, ddy in offsets
                    if 0 <= nx + ddx < w and 0 <= ny + ddy < h and out[ny + ddy, nx + ddx] > 0
                )
                if ndeg >= 3:
                    to_remove.append((y, x))
        if not to_remove:
            break
        for y, x in to_remove:
            out[y, x] = 0
    return out


def _merge_nearby_strokes(
    strokes: List[List[Tuple[float, float]]], max_gap_px: float = 2.5
) -> List[List[Tuple[float, float]]]:
    """끝점이 아주 가까운 인접 획을 이어 원·곡선 중간에 펜을 들었다 놓지 않게 합니다."""
    if len(strokes) <= 1:
        return strokes
    remaining = [list(s) for s in strokes]
    merged: List[List[Tuple[float, float]]] = [remaining.pop(0)]
    while remaining:
        cur = merged[-1]
        cx, cy = cur[-1]
        best_idx = -1
        best_dist = max_gap_px
        best_rev = False
        for i, cand in enumerate(remaining):
            d_start = math.hypot(cand[0][0] - cx, cand[0][1] - cy)
            d_end = math.hypot(cand[-1][0] - cx, cand[-1][1] - cy)
            if d_start <= best_dist:
                best_dist = d_start
                best_idx = i
                best_rev = False
            if d_end <= best_dist:
                best_dist = d_end
                best_idx = i
                best_rev = True
        if best_idx >= 0:
            nxt = remaining.pop(best_idx)
            if best_rev:
                nxt.reverse()
            cur.extend(nxt[1:] if best_dist < 1.0 else nxt)
        else:
            merged.append(remaining.pop(0))
    return merged


def _trace_skeleton_strokes(skel: np.ndarray, mask: np.ndarray) -> List[List[Tuple[float, float]]]:
    """원/곡선은 픽셀 단위 추적으로 끊김 없이 1개의 연속 선으로 잇고, 미세 점 노이즈는 제거합니다."""
    h, w = skel.shape
    ys, xs = np.where(skel > 0)
    if len(xs) == 0:
        return []

    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

    fg = set(zip(xs.tolist(), ys.tolist()))
    # 4방향 직교 이웃을 우선 탐색해 곡선 계단 구간의 3픽셀 삼각형 잔선 생성을 방지
    offsets = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)]
    adj: Dict[Tuple[int, int], List[Tuple[int, int]]] = {
        (x, y): [(x + dx, y + dy) for dx, dy in offsets if (x + dx, y + dy) in fg]
        for x, y in fg
    }

    endpoints = sorted((p for p, nb in adj.items() if len(nb) == 1), key=lambda p: (p[1], p[0]))
    others = sorted((p for p, nb in adj.items() if len(nb) != 1), key=lambda p: (p[1], p[0]))

    visited: set[Tuple[int, int]] = set()
    strokes: List[List[Tuple[float, float]]] = []

    for start in endpoints + others:
        if start in visited:
            continue
        nbs = [nb for nb in adj[start] if nb not in visited]
        if not nbs:
            # 1픽셀 단독 점은 원본 마스크 면적이 충분한 실제 점(., !, ?, i, j 등)일 때만 유지
            visited.add(start)
            lbl = int(labels[start[1], start[0]])
            if lbl > 0 and int(stats[lbl, cv2.CC_STAT_AREA]) >= _MIN_DOT_MASK_AREA:
                # 같은 연결 요소에 이미 획이 있으면 중복 점을 찍지 않음
                already_has_stroke = any(
                    int(labels[int(round(p[1])), int(round(p[0]))]) == lbl
                    for st in strokes
                    for p in st
                )
                if not already_has_stroke:
                    strokes.append([(float(start[0]), float(start[1])), (float(start[0]) + 0.5, float(start[1]))])
            continue

        visited.add(start)
        nxt = nbs[0]
        visited.add(nxt)
        stroke: List[Tuple[float, float]] = [
            (float(start[0]), float(start[1])),
            (float(nxt[0]), float(nxt[1])),
        ]
        prev, curr = start, nxt
        while True:
            cands = [nb for nb in adj[curr] if nb not in visited]
            if not cands:
                break
            vx, vy = curr[0] - prev[0], curr[1] - prev[1]
            # 직교 이웃을 우선하면서 진행 방향과 가장 일직선인 픽셀 선택
            best = max(
                cands,
                key=lambda nb: (
                    ((nb[0] - curr[0]) * vx + (nb[1] - curr[1]) * vy)
                    / max(1e-6, math.hypot(nb[0] - curr[0], nb[1] - curr[1]))
                )
                + (0.25 if abs(nb[0] - curr[0]) + abs(nb[1] - curr[1]) == 1 else 0.0),
            )
            visited.add(best)
            stroke.append((float(best[0]), float(best[1])))
            prev, curr = curr, best

        # 닫힌 곡선(원 등)이면 시작점으로 자연스럽게 닫음
        if len(stroke) >= 4 and start in adj[curr]:
            stroke.append((float(start[0]), float(start[1])))

        arc_len = sum(
            math.hypot(stroke[i + 1][0] - stroke[i][0], stroke[i + 1][1] - stroke[i][1])
            for i in range(len(stroke) - 1)
        )
        if arc_len >= 8.0:
            strokes.append(stroke)

    strokes = _merge_nearby_strokes(strokes, max_gap_px=2.5)

    # 같은 획(연결 요소)에서 떨어져 나온 15px 미만의 짧은 잔선/세리프 노이즈는 제거
    stroke_labels = [
        int(labels[int(round(st[0][1])), int(round(st[0][0]))]) for st in strokes
    ]
    stroke_lens = [
        sum(math.hypot(st[i + 1][0] - st[i][0], st[i + 1][1] - st[i][1]) for i in range(len(st) - 1))
        for st in strokes
    ]
    max_len_by_label: Dict[int, float] = {}
    for lbl, slen in zip(stroke_labels, stroke_lens):
        if lbl > 0:
            max_len_by_label[lbl] = max(max_len_by_label.get(lbl, 0.0), slen)
    strokes = [
        st
        for st, lbl, slen in zip(strokes, stroke_labels, stroke_lens)
        if slen >= 15.0 or lbl == 0 or max_len_by_label.get(lbl, 0.0) < 25.0
    ]

    simplified: List[List[Tuple[float, float]]] = []
    for st in strokes:
        if len(st) <= 2:
            simplified.append(st)
            continue
        is_closed = math.hypot(st[0][0] - st[-1][0], st[0][1] - st[-1][1]) <= 2.0
        arr = np.array(st[:-1] if is_closed and len(st) > 3 else st, dtype=np.float32).reshape(-1, 1, 2)
        approx = cv2.approxPolyDP(arr, epsilon=0.5, closed=is_closed).reshape(-1, 2)
        pts = [(float(x), float(y)) for x, y in approx]
        if is_closed and len(pts) >= 2:
            pts.append(pts[0])
        if len(pts) >= 2:
            simplified.append(_orient_human_stroke(pts))

    simplified.sort(key=lambda s: (s[0][0] + 0.85 * s[0][1], s[0][1], s[0][0]))
    return simplified


def _orient_human_stroke(pts: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """사람이 글씨를 쓰는 방향(위->아래, 왼->오, 닫힌 원은 위에서 반시계)으로 획 방향을 맞춥니다."""
    if len(pts) < 2:
        return pts
    is_closed = len(pts) >= 4 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 2.0
    if is_closed:
        ring = list(pts[:-1])
        n = len(ring)
        if n >= 3:
            area2 = sum(
                (ring[(i + 1) % n][0] - ring[i][0]) * (ring[(i + 1) % n][1] + ring[i][1])
                for i in range(n)
            )
            if area2 < 0:
                ring.reverse()
            top_idx = min(range(n), key=lambda i: (ring[i][1], ring[i][0]))
            ring = ring[top_idx:] + ring[:top_idx]
        return ring + [ring[0]]

    x0, y0 = pts[0]
    x1, y1 = pts[-1]
    dx, dy = x1 - x0, y1 - y0
    if abs(dy) >= 0.45 * abs(dx) and abs(dy) >= 6.0:
        return list(reversed(pts)) if dy < 0 else pts
    if dx < 0 or (abs(dx) < 1e-6 and dy < 0):
        return list(reversed(pts))
    return pts


def _sample_radius(dist: np.ndarray, x: float, y: float) -> float:
    """거리 변환 맵에서 (x, y) 주변 3x3 최대 반지름(선 두께의 절반)을 읽습니다."""
    h, w = dist.shape
    cx = max(0, min(w - 1, int(round(x))))
    cy = max(0, min(h - 1, int(round(y))))
    x0, x1 = max(0, cx - 1), min(w, cx + 2)
    y0, y1 = max(0, cy - 1), min(h, cy + 2)
    return float(np.max(dist[y0:y1, x0:x1]))


def _subdivide_and_sample_radii(
    pts: List[Tuple[float, float]], dist: np.ndarray
) -> Tuple[List[Tuple[float, float]], List[float]]:
    """긴 직선 구간을 세분화하고 각 꼭짓점의 폰트 선 반지름을 추출합니다."""
    if len(pts) < 2:
        return pts, [_sample_radius(dist, p[0], p[1]) for p in pts]
    dense: List[Tuple[float, float]] = [pts[0]]
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        seg_len = math.hypot(x1 - x0, y1 - y0)
        if seg_len > _MAX_THICKNESS_SAMPLE_SEG_PX:
            steps = int(math.ceil(seg_len / _MAX_THICKNESS_SAMPLE_SEG_PX))
            for s in range(1, steps):
                t = s / steps
                dense.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        dense.append((x1, y1))
    radii = [_sample_radius(dist, x, y) for x, y in dense]
    return dense, radii


def _render_char_strokes(
    ch: str, font: ImageFont.FreeTypeFont, max_ascent: int
) -> List[Tuple[List[Tuple[float, float]], List[float]]]:
    """단일 문자를 렌더링해 (스켈레톤 획, 점별 선 반지름) 리스트를 반환합니다."""
    ascent, descent = font.getmetrics()
    adv = max(float(font.getlength(ch)), 10.0)
    canvas_w = max(32, int(math.ceil(adv)) + _PADDING * 2)
    canvas_h = max(32, max_ascent + descent + _PADDING * 2)
    img = Image.new("L", (canvas_w, canvas_h), 0)
    draw = ImageDraw.Draw(img)
    baseline_y = _PADDING + max_ascent
    draw.text((_PADDING, baseline_y - ascent), ch, fill=255, font=font)

    mask = (np.array(img) > 127).astype(np.uint8)
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    skel = _zhang_suen_thinning(mask)
    skel = _prune_spurs(skel, max_spur_len=6)
    strokes = _trace_skeleton_strokes(skel, mask)
    return [_subdivide_and_sample_radii(st, dist) for st in strokes]


def _render_text_ordered(
    text: str, candidates: Tuple[str, ...]
) -> Tuple[List[List[Tuple[float, float]]], List[List[float]], int]:
    """문자 단위로 렌더링·추적하여 왼쪽에서 오른쪽 순서가 반드시 유지되게 합니다."""
    glyph_runs: List[Tuple[str, Optional[ImageFont.FreeTypeFont], float]] = []
    max_ascent = 0

    for ch in text:
        if ord(ch) < 32:
            raise ValueError("제어 문자나 줄바꿈은 입력할 수 없습니다.")
        if ch.isspace():
            glyph_runs.append((ch, None, _RENDER_SIZE * 0.4))
            continue
        font_path = _select_font_for_char(ch, candidates)
        if font_path is None:
            raise ValueError(f"지원하지 않는 문자입니다: {ch!r}")
        font = _load_pil_font(font_path, _RENDER_SIZE)
        ascent, _ = font.getmetrics()
        max_ascent = max(max_ascent, ascent)
        adv = max(float(font.getlength(ch)), 10.0)
        glyph_runs.append((ch, font, adv))

    all_strokes: List[List[Tuple[float, float]]] = []
    all_radii: List[List[float]] = []
    cursor_x = 0.0
    baseline_y = _PADDING + max_ascent
    for ch, font, adv in glyph_runs:
        if font is not None:
            char_strokes = _render_char_strokes(ch, font, max_ascent)
            for st, radii in char_strokes:
                all_strokes.append([(cursor_x + (px - _PADDING), py) for px, py in st])
                all_radii.append(radii)
        cursor_x += adv

    return all_strokes, all_radii, baseline_y


def generate_strokes(
    text: str,
    *,
    origin: Tuple[float, float] = (15.0, 270.0),
    height_mm: float = 16.0,
    pen_id: str = "PEN_4",
    bounds_mm: Optional[Tuple[float, float, float, float]] = None,
    paper_size_mm: Tuple[float, float] = (210.0, 297.0),
) -> List[dict]:
    """한글·영문·숫자·특수문자를 왼쪽부터 순서대로 종이 mm 경로로 변환합니다."""
    if not isinstance(text, str) or len(text) > 120:
        raise ValueError("문구는 120자 이하의 문자열이어야 합니다.")
    if not math.isfinite(height_mm) or not 0 < height_mm <= 30 or pen_id not in ("PEN_1", "PEN_2", "PEN_3", "PEN_4"):
        raise ValueError("잘못된 문자 크기 또는 펜입니다.")
    if not text.strip():
        return []

    candidates = _font_candidates()
    if not candidates:
        raise RuntimeError("시스템에 사용 가능한 트루타입 폰트가 없습니다.")

    raw_strokes, raw_radii, baseline_y = _render_text_ordered(text, candidates)
    if not raw_strokes:
        return []

    flat_radii = [r for rs in raw_radii for r in rs]
    min_r = min(flat_radii) if flat_radii else 0.0
    max_r = max(flat_radii) if flat_radii else 0.0
    radius_span = max(max_r - min_r, 2.0)

    all_x = [p[0] for st in raw_strokes for p in st]
    all_y = [p[1] for st in raw_strokes for p in st]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    span_x = max(1.0, max_x - min_x)
    span_y = max(1.0, max_y - min_y)

    scale = height_mm / max(_RENDER_SIZE * 0.72, span_y)
    ox, base_mm = origin

    if bounds_mm is not None:
        left, top, right, bottom = bounds_mm
        avail_w = max(1.0, right - left)
        avail_h = max(1.0, bottom - top)
        if span_x * scale > avail_w:
            scale = avail_w / span_x
        if span_y * scale > avail_h:
            scale = min(scale, avail_h / span_y)
        start_x = left
        start_y = top + max(0.0, (avail_h - span_y * scale) * 0.5)
    else:
        start_x = ox
        start_y = base_mm - (baseline_y - min_y) * scale

    strokes: List[dict] = []
    for st, radii in zip(raw_strokes, raw_radii):
        points = [
            [
                round(start_x + (px - min_x) * scale, 3),
                round(start_y + (py - min_y) * scale, 3),
            ]
            for px, py in st
        ]
        if any(not (0 <= x <= paper_size_mm[0] and 0 <= y <= paper_size_mm[1]) for x, y in points):
            raise ValueError("문구가 A4 범위를 벗어납니다.")
        z_deltas = [
            round(
                MIN_THICKNESS_Z_DELTA_MM
                + (MAX_THICKNESS_Z_DELTA_MM - MIN_THICKNESS_Z_DELTA_MM)
                * max(0.0, min(1.0, (r - min_r) / radius_span)),
                3,
            )
            for r in radii
        ]
        strokes.append(dict(pen_id=pen_id, layer="calligraphy", points_mm=points, z_deltas_mm=z_deltas))
    return strokes
