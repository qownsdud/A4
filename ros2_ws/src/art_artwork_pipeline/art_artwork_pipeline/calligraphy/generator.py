"""한글·영문·숫자·특수문자 및 다국어 문자를 폰트 스켈레톤 기반 종이 mm 경로로 변환합니다."""

from __future__ import annotations

from functools import lru_cache
import math
import os
from pathlib import Path
import subprocess
from typing import Dict, List, Optional, Tuple
import unicodedata

import cv2
from fontTools.ttLib import TTFont
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _a4_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "ros2_ws":
            return parent.parent
    return Path.cwd()


_DEFAULT_FONT_CANDIDATES = (
    str(_a4_root() / "assets/fonts/NanumBrush.ttf"),
    str(Path.home() / ".local/share/fonts/NanumBrush.ttf"),
    "/usr/share/fonts/truetype/nanum/NanumBrush.ttf",
    # 붓글씨 폰트가 지원하지 않는 언어(유럽어·러시아어·그리스어·일어·중어·태국어·아랍어·기호 등)는 깔끔한 정자체 Regular 우선
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansMath-Regular.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

_RENDER_SIZE = 140
_PADDING = 20
_MIN_DOT_MASK_AREA = 15
MIN_THICKNESS_Z_DELTA_MM = 0.7   # 가장 얇은 구간: 기준 높이보다 +0.7mm 상승
MAX_THICKNESS_Z_DELTA_MM = -1.3  # 가장 두꺼운 구간: 기준 높이보다 -1.3mm 하강
_MAX_THICKNESS_SAMPLE_SEG_PX = 8.0
_UNSUPPORTED_FONT_KEYWORDS = ("coloremoji", "emojione", "twemoji", "notoemoji")


def _font_candidates() -> Tuple[str, ...]:
    env_font = os.environ.get("ART_CALLIGRAPHY_FONT", "").strip()
    candidates = ([env_font] if env_font else []) + list(_DEFAULT_FONT_CANDIDATES)
    seen: set[str] = set()
    out: List[str] = []
    for p in candidates:
        if p and p not in seen and Path(p).is_file():
            seen.add(p)
            out.append(p)
    return tuple(out)


def _is_brush_char(ch: str) -> bool:
    """NanumBrush에서 실제 붓글씨 가변 굵기를 갖는 한글·영문·숫자·기본 기호 영역인지 확인합니다."""
    code = ord(ch)
    return (
        0x0021 <= code <= 0x007E  # ASCII 영문·숫자·기본 문장부호
        or 0x1100 <= code <= 0x11FF  # 한글 자모
        or 0x3130 <= code <= 0x318F  # 한글 호환 자모
        or 0xAC00 <= code <= 0xD7A3  # 한글 완성형
    )


def _is_brush_font(font_path: str, unit: str = "") -> bool:
    """붓글씨(가변 굵기) 폰트 및 붓글씨 대상 문자인지 판별합니다. 기타 언어는 균일 굵기로 깔끔하게 그립니다."""
    name = Path(font_path).name.lower()
    if not any(tok in name for tok in ("brush", "pen", "callig", "script")):
        return False
    return bool(unit) and all(_is_brush_char(c) for c in unit)


@lru_cache(maxsize=64)
def _load_cmap(font_path: str) -> set[int]:
    try:
        with TTFont(font_path, fontNumber=0) as tt:
            cmap = tt.getBestCmap()
            return set(cmap.keys()) if cmap else set()
    except Exception:
        return set()


@lru_cache(maxsize=64)
def _load_pil_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path, size)


@lru_cache(maxsize=2048)
def _has_visible_glyph(font_path: str, code: int) -> bool:
    """cmap에만 등록되고 실제 외곽선/픽셀이 비어 있는 빈 글리프(예: NanumBrush의 한자 슬롯)를 걸러냅니다."""
    try:
        font = _load_pil_font(font_path, _RENDER_SIZE)
        mask = font.getmask(chr(code))
        return mask.getbbox() is not None
    except Exception:
        return False


def _is_usable_vector_font(font_path: str, code: int) -> bool:
    if not font_path or not Path(font_path).is_file():
        return False
    low = font_path.lower()
    if any(bad in low for bad in _UNSUPPORTED_FONT_KEYWORDS):
        return False
    if not low.endswith((".ttf", ".otf", ".ttc")):
        return False
    if code not in _load_cmap(font_path):
        return False
    return _has_visible_glyph(font_path, code)


@lru_cache(maxsize=256)
def _find_fontconfig_font(code: int) -> Optional[str]:
    """fontconfig(fc-match / fc-list)로 시스템에 설치된 다국어 정자체 벡터 폰트를 동적 탐색합니다."""
    hex_cp = f"{code:x}"
    queries = (
        ["fc-match", "-f", "%{file}\n", f":charset={hex_cp}:family=sans-serif:weight=regular"],
        ["fc-match", "-f", "%{file}\n", f":charset={hex_cp}:weight=regular"],
        ["fc-list", f":charset={hex_cp}", "file"],
    )
    for cmd in queries:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
        except (OSError, subprocess.SubprocessError):
            continue
        if res.returncode != 0:
            continue
        lines = [line.split(":", 1)[0].strip() for line in res.stdout.splitlines() if line.strip()]
        # Regular / Sans 스타일을 우선 선택
        lines.sort(
            key=lambda p: (
                0 if "regular" in p.lower() else 1,
                0 if "sans" in p.lower() else 1,
                1 if "bold" in p.lower() else 0,
            )
        )
        for path in lines:
            if _is_usable_vector_font(path, code):
                return path
    return None


def _select_font_for_char(ch: str, candidates: Tuple[str, ...]) -> Optional[str]:
    code = ord(ch)
    for path in candidates:
        if _is_usable_vector_font(path, code):
            return path
    return _find_fontconfig_font(code)


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
    """엣지 기반 추적으로 교차점·분기점 누락 없이 연속 획을 추출하고, 미세 점 노이즈만 제거합니다."""
    ys, xs = np.where(skel > 0)
    if len(xs) == 0:
        return []

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

    fg = set(zip(xs.tolist(), ys.tolist()))
    ortho_offsets = ((1, 0), (-1, 0), (0, 1), (0, -1))
    diag_offsets = ((1, 1), (-1, -1), (1, -1), (-1, 1))
    adj: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for x, y in fg:
        nbs = [(x + dx, y + dy) for dx, dy in ortho_offsets if (x + dx, y + dy) in fg]
        for dx, dy in diag_offsets:
            nx, ny = x + dx, y + dy
            if (nx, ny) in fg and (x + dx, y) not in fg and (x, y + dy) not in fg:
                nbs.append((nx, ny))
        adj[(x, y)] = nbs

    def make_edge(a: Tuple[int, int], b: Tuple[int, int]) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        return (a, b) if a <= b else (b, a)

    endpoints = sorted((p for p, nb in adj.items() if len(nb) == 1), key=lambda p: (p[1], p[0]))
    junctions = sorted((p for p, nb in adj.items() if len(nb) >= 3), key=lambda p: (p[1], p[0]))
    others = sorted((p for p, nb in adj.items() if len(nb) == 2), key=lambda p: (p[1], p[0]))
    isolated = sorted((p for p, nb in adj.items() if len(nb) == 0), key=lambda p: (p[1], p[0]))

    used_edges: set[Tuple[Tuple[int, int], Tuple[int, int]]] = set()
    strokes: List[List[Tuple[float, float]]] = []

    for start in endpoints + junctions + others + isolated:
        if not adj[start]:
            # 1픽셀 단독 점은 원본 마스크 면적이 충분한 실제 점(., !, ?, i, j 등)일 때만 유지
            lbl = int(labels[start[1], start[0]])
            if lbl > 0 and int(stats[lbl, cv2.CC_STAT_AREA]) >= _MIN_DOT_MASK_AREA:
                already_has_stroke = any(
                    int(labels[int(round(p[1])), int(round(p[0]))]) == lbl
                    for st in strokes
                    for p in st
                )
                if not already_has_stroke:
                    strokes.append([(float(start[0]), float(start[1])), (float(start[0]) + 0.5, float(start[1]))])
            continue

        for nxt in adj[start]:
            if make_edge(start, nxt) in used_edges:
                continue
            used_edges.add(make_edge(start, nxt))
            stroke: List[Tuple[float, float]] = [
                (float(start[0]), float(start[1])),
                (float(nxt[0]), float(nxt[1])),
            ]
            curr = nxt
            while curr != start:
                cands = [nb for nb in adj[curr] if make_edge(curr, nb) not in used_edges]
                if not cands:
                    break
                if len(adj[curr]) == 2:
                    best = cands[0]
                else:
                    ref_idx = max(0, len(stroke) - 5)
                    vx = curr[0] - stroke[ref_idx][0]
                    vy = curr[1] - stroke[ref_idx][1]
                    vn = math.hypot(vx, vy)
                    if vn < 1e-6:
                        break
                    scored = [
                        (
                            ((nb[0] - curr[0]) * vx + (nb[1] - curr[1]) * vy)
                            / (max(1e-6, math.hypot(nb[0] - curr[0], nb[1] - curr[1])) * vn),
                            nb,
                        )
                        for nb in cands
                    ]
                    best_cos, best = max(scored, key=lambda item: item[0])
                    if best_cos < 0.60:
                        break
                used_edges.add(make_edge(curr, best))
                stroke.append((float(best[0]), float(best[1])))
                curr = best

            arc_len = sum(
                math.hypot(stroke[i + 1][0] - stroke[i][0], stroke[i + 1][1] - stroke[i][1])
                for i in range(len(stroke) - 1)
            )
            lbl = int(labels[int(round(stroke[0][1])), int(round(stroke[0][0]))])
            is_valid_dot = lbl > 0 and int(stats[lbl, cv2.CC_STAT_AREA]) >= _MIN_DOT_MASK_AREA
            if arc_len >= 6.0 or is_valid_dot:
                strokes.append(stroke)

    strokes = _merge_nearby_strokes(strokes, max_gap_px=2.5)

    # Zhang-Suen 세선화에서 대칭 원형 점(Ü/Ö/Ä 움라우트, 아랍어 점, 마침표 등)이 0픽셀로 소실된 경우 중심점으로 복구
    covered_labels = {
        int(labels[int(round(p[1])), int(round(p[0]))])
        for st in strokes
        for p in st
        if 0 <= int(round(p[1])) < labels.shape[0] and 0 <= int(round(p[0])) < labels.shape[1]
    }
    for lbl in range(1, num_labels):
        if lbl not in covered_labels and int(stats[lbl, cv2.CC_STAT_AREA]) >= _MIN_DOT_MASK_AREA:
            cx, cy = float(centroids[lbl][0]), float(centroids[lbl][1])
            strokes.append([(cx - 0.5, cy), (cx + 0.5, cy)])

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


def _is_combining(ch: str) -> bool:
    return unicodedata.category(ch) in ("Mn", "Mc", "Me") or ch in ("\u200d", "\ufe0e", "\ufe0f")


def _is_connected_rtl(ch: str) -> bool:
    code = ord(ch)
    return (
        0x0590 <= code <= 0x05FF  # Hebrew
        or 0x0600 <= code <= 0x06FF  # Arabic
        or 0x0750 <= code <= 0x077F  # Arabic Supplement
        or 0x08A0 <= code <= 0x08FF  # Arabic Extended
    )


def _split_text_units(text: str) -> List[str]:
    """결합 발음기호(태국어·힌디어·비라마 합자 등)는 기본 문자에 붙이고, 아랍어·히브리어 연속 단어는 묶어 셰이핑합니다."""
    units: List[str] = []
    for ch in text:
        if ord(ch) < 32:
            raise ValueError("제어 문자나 줄바꿈은 입력할 수 없습니다.")
        if ch.isspace():
            units.append(ch)
        elif units and not units[-1].isspace() and (
            _is_combining(ch) or unicodedata.combining(units[-1][-1]) == 9
        ):
            units[-1] += ch
        elif _is_connected_rtl(ch) and units and _is_connected_rtl(units[-1][0]):
            units[-1] += ch
        else:
            units.append(ch)
    return units


def _render_unit_strokes(
    unit: str, font: ImageFont.FreeTypeFont, max_ascent: int, is_brush: bool
) -> List[Tuple[List[Tuple[float, float]], List[float]]]:
    """단일 문자(또는 결합 클러스터/아랍어 단어)를 잘림 없이 렌더링해 (획, 반지름) 리스트를 반환합니다."""
    ascent, descent = font.getmetrics()
    adv = max(float(font.getlength(unit)), 10.0)
    try:
        bbox = font.getbbox(unit)
    except Exception:
        bbox = (0, 0, int(math.ceil(adv)), ascent + descent)
    pad_left = _PADDING + max(0, int(math.ceil(-bbox[0])))
    pad_top = _PADDING + max(0, int(math.ceil(-bbox[1])))
    right_ext = max(int(math.ceil(adv)), int(math.ceil(bbox[2])))
    bottom_ext = max(ascent + descent, int(math.ceil(bbox[3])))

    canvas_w = max(32, pad_left + right_ext + _PADDING)
    canvas_h = max(32, pad_top + max(0, max_ascent - ascent) + bottom_ext + _PADDING)
    img = Image.new("L", (canvas_w, canvas_h), 0)
    draw = ImageDraw.Draw(img)
    draw_y = pad_top + (max_ascent - ascent)
    draw.text((pad_left, draw_y), unit, fill=255, font=font)

    mask = (np.array(img) > 127).astype(np.uint8)
    if not np.any(mask):
        return []
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    skel = _zhang_suen_thinning(mask)
    strokes = _trace_skeleton_strokes(skel, mask)
    out: List[Tuple[List[Tuple[float, float]], List[float]]] = []
    for st in strokes:
        if is_brush:
            dense, radii = _subdivide_and_sample_radii(st, dist)
        else:
            dense = list(st)
            radii = [0.0] * len(dense)
        shifted = [(px - pad_left, py - pad_top) for px, py in dense]
        out.append((shifted, radii))
    return out


def _render_text_ordered(
    text: str, candidates: Tuple[str, ...]
) -> Tuple[List[List[Tuple[float, float]]], List[List[float]], List[bool], int]:
    """문자/클러스터 단위로 렌더링·추적하여 왼쪽에서 오른쪽 순서와 다국어 가독성을 모두 유지합니다."""
    normalized = unicodedata.normalize("NFC", text)
    units = _split_text_units(normalized)
    glyph_runs: List[Tuple[str, Optional[ImageFont.FreeTypeFont], float, bool]] = []
    max_ascent = 0

    for unit in units:
        if unit.isspace():
            glyph_runs.append((unit, None, _RENDER_SIZE * 0.4, False))
            continue
        base_ch = unit[0]
        font_path = _select_font_for_char(base_ch, candidates)
        # 결합 문자가 포함된 클러스터는 모든 문자를 지원하는 대체 정자체 폰트를 우선 선택
        if font_path is not None and len(unit) > 1:
            cmap = _load_cmap(font_path)
            if any(ord(c) not in cmap for c in unit if c not in ("\u200d", "\ufe0e", "\ufe0f")):
                alt = _find_fontconfig_font(ord(base_ch))
                if alt is not None:
                    font_path = alt
        if font_path is None:
            raise ValueError(f"지원하지 않는 문자입니다: {unit!r}")
        font = _load_pil_font(font_path, _RENDER_SIZE)
        ascent, _ = font.getmetrics()
        max_ascent = max(max_ascent, ascent)
        adv = max(float(font.getlength(unit)), 10.0)
        glyph_runs.append((unit, font, adv, _is_brush_font(font_path, unit)))

    all_strokes: List[List[Tuple[float, float]]] = []
    all_radii: List[List[float]] = []
    all_is_brush: List[bool] = []
    cursor_x = 0.0
    baseline_y = max_ascent
    for unit, font, adv, is_brush in glyph_runs:
        if font is not None:
            unit_strokes = _render_unit_strokes(unit, font, max_ascent, is_brush)
            for st, radii in unit_strokes:
                all_strokes.append([(cursor_x + px, py) for px, py in st])
                all_radii.append(radii)
                all_is_brush.append(is_brush)
        cursor_x += adv

    return all_strokes, all_radii, all_is_brush, baseline_y


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

    raw_strokes, raw_radii, raw_is_brush, baseline_y = _render_text_ordered(text, candidates)
    if not raw_strokes:
        return []

    flat_brush_radii = [r for rs, is_b in zip(raw_radii, raw_is_brush) if is_b for r in rs]
    min_r = min(flat_brush_radii) if flat_brush_radii else 0.0
    max_r = max(flat_brush_radii) if flat_brush_radii else 0.0
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
    for st, radii, is_brush in zip(raw_strokes, raw_radii, raw_is_brush):
        points = [
            [
                round(start_x + (px - min_x) * scale, 3),
                round(start_y + (py - min_y) * scale, 3),
            ]
            for px, py in st
        ]
        if any(not (0 <= x <= paper_size_mm[0] and 0 <= y <= paper_size_mm[1]) for x, y in points):
            raise ValueError("문구가 A4 범위를 벗어납니다.")
        if is_brush:
            z_deltas = [
                round(
                    MIN_THICKNESS_Z_DELTA_MM
                    + (MAX_THICKNESS_Z_DELTA_MM - MIN_THICKNESS_Z_DELTA_MM)
                    * max(0.0, min(1.0, (r - min_r) / radius_span)),
                    3,
                )
                for r in radii
            ]
        else:
            # 붓글씨 미지원 언어(정자체 대체 폰트)는 굵기 왜곡 없이 균일한 선 높이(0.0mm)로 깔끔하게 따라 그립니다.
            z_deltas = [0.0] * len(points)
        # 마침표·느낌표·물음표 등의 짧은 점 획(<2.5mm)은 종이에서 뜨지 않도록 Z<=0으로 눌러 찍습니다.
        stroke_mm_len = sum(
            math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
            for i in range(len(points) - 1)
        )
        if stroke_mm_len < 2.5:
            z_deltas = [min(-0.3, dz) for dz in z_deltas]
        strokes.append(dict(pen_id=pen_id, layer="calligraphy", points_mm=points, z_deltas_mm=z_deltas))
    return strokes
