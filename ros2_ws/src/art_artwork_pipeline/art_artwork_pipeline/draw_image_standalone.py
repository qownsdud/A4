#!/usr/bin/env python3
"""독립 실행형 멀티펜 이미지 드로잉 노드 (외부 패키지/내부 모듈 의존성 없음).

기능 요약:
1. 입력 이미지(PNG/JPG) -> 세선화(Zhang-Suen) + 경로 추출 -> 벡터 획(strokes) 생성
   (이미 변환된 *_strokes.json 입력도 그대로 지원)
2. A4/config/plane_calibration.json의 9점 영역 내 안전 직사각형에 비율 유지 중앙 배치
3. 전체 획을 3개 펜에 균등 분배
4. 기준 막대로 바닥 높이(Z) 포스 접촉 측정 후, 펜 1·2·3이 순서대로 나눠 그림

실행 예:
- python3 draw_image_standalone.py --input /path/to/image.png
- python3 draw_image_standalone.py --dry-run   # 로봇 이동 없이 변환·배치 결과만 확인
- ros2 run collaborate1 draw_image_standalone
"""

import argparse
from datetime import datetime
import json
import math
import os
import select
import shutil
import sys
import termios
import threading
import time
import tty
from typing import Dict, List, Optional, Set, Tuple

import cv2
import numpy as np

# =============================================================================
# 1. 로봇 및 작업 파라미터 설정
# =============================================================================
ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"

# 속도 / 가속도
J_VEL, J_ACC = 60, 60            # Joint 이동 (deg/s, deg/s^2)
L_VEL, L_ACC = 80, 80            # 공중 이동 (mm/s, mm/s^2)
PICK_VEL, PICK_ACC = 25, 25      # 픽앤플레이스 하강/상승 (mm/s, mm/s^2)
PROBE_VEL, PROBE_ACC = 5, 5      # 기준 막대 바닥 탐색 (mm/s, mm/s^2)
DRAW_VEL, DRAW_ACC = 25, 25      # 그리기 (mm/s, mm/s^2)
CORNER_ANGLE_DEG = 35.0          # 이 각도(deg) 이상 꺾이는 점은 각진 모서리로 보고 movel로 정지
MOVESX_MAX_POINTS = 80           # movesx 1회 호출당 최대 경유점 수

# 홈 / 대기 및 접근 오프셋
HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
READY_OFFSET = [0.0, 0.0, -100.0, 0.0, 0.0, 0.0]
APPROACH_OFFSET_Z = 100.0        # 슬롯 접근 시 위 +100 mm
STROKE_LIFT_MM = 15.0            # 펜 진입 전후 안전 상승 높이 (mm)
IMAGE_STROKE_LIFT_MM = 4.0       # 획 전환 시 공중 이동 높이 (mm)
# 기준 막대 집기/놓기 시 세 번째 펜과의 간섭 회피용 J6(툴 Z축) 회전 오프셋 (deg)
# Tool Z가 바닥(-Base Z)을 향하므로 rz -45° = Base +Z축 기준 +45°(위에서 봤을 때 반시계) 회전
STICK_GRIP_RZ_OFFSET_DEG = -45.0

# 기준 막대 포스 접촉 감지 파라미터
PROBE_STEP_MM = 0.5
PROBE_FINE_STEP_MM = 0.1
PROBE_MAX_TRAVEL_MM = 20.0
WARMUP_STEPS = 2
SETTLE_TIME_S = 0.12
READ_SAMPLES = 3
SAMPLE_INTERVAL_S = 0.03
CONTACT_FORCE_DELTA_N = 2.5
HARD_LIMIT_FORCE_N = 60.0
CONFIRM_COUNT = 2
BASELINE_SAMPLES = 10
CONTACT_SIGN = +1

# 9점 빈 그리퍼 자동 재캘리브레이션 파라미터
AUTO_CALIBRATE_9PT = False        # True: 시작 시 닫힌 빈 그리퍼로 9점 Z를 새로 재서 기울기(a, b) 갱신
CALIBRATE_INSET_MM = 40.0        # 무게추 회피를 위해 모서리/변 점을 중심 쪽으로 당길 거리 (mm)
GRIPPER_PROBE_START_OFFSET_Z = 15.0  # 첫 점 탐색 시작 높이 오프셋 (+mm)
GRIPPER_PROBE_MAX_TRAVEL_MM = 30.0   # 빈 그리퍼 최대 하강 탐색 거리 (mm)

# 펜 1, 2, 3, 4(글씨용 검정) 그리기 높이 오프셋 및 안전 여백
PEN_Z_OFFSETS = [12.5, 12.5, 12.5, 12.5]
RECT_MARGIN_MM = 20.0

# 이미지 벡터화 파라미터 (image_vectorizer.py 방식 — 원본 선 형태 보존 우선)
VECTORIZE_THRESHOLD = 180        # 그레이스케일 이진화 임계값 (gray < threshold)
VECTORIZE_MAX_SPUR_LEN = 3       # 세선화 분기점 잔가지(spur) 제거 길이 (px)
VECTORIZE_EPSILON_PX = 0.6       # Douglas-Peucker 단순화 허용 오차 (px)
VECTORIZE_MIN_LEN_PX = 4.0       # 노이즈성 짧은 점/획 제거 기준 (px)
VECTORIZE_MERGE_DIST_PX = 0.0    # 서로 떨어진 별도 획을 임의로 이어붙이지 않음
CHAIKIN_ITERATIONS = 1           # Chaikin 코너 절단 스무딩 반복 횟수
SORT_NEAREST_STROKES = True      # 펜별 그룹 내 공중 이동 최소화 정렬

# 기본 파일 경로
def _a4_root() -> str:
    here = os.path.abspath(__file__)
    cur = os.path.dirname(here)
    while cur != os.path.dirname(cur):
        if os.path.basename(cur) == "ros2_ws":
            return os.path.dirname(cur)
        cur = os.path.dirname(cur)
    return os.getcwd()


def _config_file(name: str) -> str:
    config_dir = os.environ.get("ART_CONFIG_DIR", os.path.join(_a4_root(), "config"))
    return os.path.join(config_dir, name)


STICK_FILE = _config_file("stick_slot.json")
PENS_FILE = _config_file("pen_slots.json")
CALIBRATION_FILE = _config_file("plane_calibration.json")
PREVIEW_DIR = os.environ.get("ART_DRAWING_PREVIEW_DIR", os.path.join(_a4_root(), "data", "drawing_previews"))
DEFAULT_INPUT_PATH = os.path.join(_a4_root(), "data", "jobs", "latest_strokes.json")

ON, OFF = 1, 0


# =============================================================================
# 2. 이미지 -> 벡터 획 변환 (OpenCV + NumPy만 사용)
# =============================================================================
def _zhang_suen_thinning(binary: np.ndarray) -> np.ndarray:
    """이진 이미지(0/1)를 1픽셀 두께 중심선(Skeleton)으로 세선화한다."""
    img = (binary > 0).astype(np.uint8)
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


def _build_adj(skel: np.ndarray) -> Dict[Tuple[int, int], List[Tuple[int, int]]]:
    h, w = skel.shape
    ys, xs = np.where(skel > 0)
    fg = set(zip(xs.tolist(), ys.tolist()))
    offsets = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]
    return {
        (x, y): [
            (x + dx, y + dy)
            for dx, dy in offsets
            if 0 <= x + dx < w and 0 <= y + dy < h and (x + dx, y + dy) in fg
        ]
        for x, y in fg
    }


def _prune_spurs(skel: np.ndarray, max_spur_len: int = VECTORIZE_MAX_SPUR_LEN) -> np.ndarray:
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


def _trace_skeleton_strokes(skel: np.ndarray) -> List[List[Tuple[int, int]]]:
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


def _chaikin_smooth(pts: List[Tuple[float, float]], iterations: int = CHAIKIN_ITERATIONS) -> List[Tuple[float, float]]:
    """Chaikin 코너 절단 스무딩으로 픽셀 계단 현상을 부드러운 곡선으로 다듬는다."""
    cur = list(pts)
    for _ in range(iterations):
        if len(cur) < 3:
            break
        nxt: List[Tuple[float, float]] = [cur[0]]
        for i in range(len(cur) - 1):
            p0, p1 = cur[i], cur[i + 1]
            nxt.append((0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]))
            nxt.append((0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]))
        nxt.append(cur[-1])
        cur = nxt
    return cur


def _simplify_and_sort_strokes(
    strokes: List[List[Tuple[int, int]]],
    epsilon_px: float = VECTORIZE_EPSILON_PX,
    min_len_px: float = VECTORIZE_MIN_LEN_PX,
    merge_dist_px: float = VECTORIZE_MERGE_DIST_PX,
) -> List[List[Tuple[float, float]]]:
    """스무딩, RDP 단순화, 이동 최소화 정렬 및 근접 끝점 병합을 수행한다."""
    cleaned: List[List[Tuple[float, float]]] = []
    for st in strokes:
        if len(st) < 2:
            continue
        length = sum(math.hypot(st[i + 1][0] - st[i][0], st[i + 1][1] - st[i][1]) for i in range(len(st) - 1))
        if length < min_len_px:
            continue
        smoothed = _chaikin_smooth([(float(x), float(y)) for x, y in st], iterations=CHAIKIN_ITERATIONS)
        arr = np.array(smoothed, dtype=np.float32).reshape(-1, 1, 2)
        approx = cv2.approxPolyDP(arr, epsilon_px, closed=False).reshape(-1, 2)
        if len(approx) >= 2:
            cleaned.append([(float(x), float(y)) for x, y in approx])

    if not cleaned:
        return []

    ordered: List[List[Tuple[float, float]]] = []
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
        if merge_dist_px > 0 and best_dist <= merge_dist_px:
            ordered[-1].extend(nxt[1:] if best_dist < 1e-3 else nxt)
        else:
            ordered.append(nxt)

    return ordered


def load_strokes_from_input(input_path: str) -> List[List[Tuple[float, float]]]:
    """JSON(strokes_px) 또는 이미지(PNG/JPG)에서 기존 image_vectorizer 방식으로 픽셀 단위 획을 바로 추출한다."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"입력 파일이 없습니다: {input_path}")

    if input_path.lower().endswith(".json"):
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        strokes = data.get("strokes_px", [])
        if not strokes:
            raise ValueError(f"strokes_px 데이터가 비어 있습니다: {input_path}")
        return [[(float(p[0]), float(p[1])) for p in st] for st in strokes if len(st) >= 2]

    gray = cv2.imread(input_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {input_path}")

    binary = (gray < VECTORIZE_THRESHOLD).astype(np.uint8)
    skel = _zhang_suen_thinning(binary)
    skel = _prune_spurs(skel, max_spur_len=VECTORIZE_MAX_SPUR_LEN)
    raw_strokes = _trace_skeleton_strokes(skel)
    strokes = _simplify_and_sort_strokes(
        raw_strokes,
        epsilon_px=VECTORIZE_EPSILON_PX,
        min_len_px=VECTORIZE_MIN_LEN_PX,
        merge_dist_px=VECTORIZE_MERGE_DIST_PX,
    )
    if not strokes:
        raise ValueError(f"이미지에서 추출된 획이 없습니다: {input_path}")
    return strokes


def save_drawing_preview(
    pen_groups: List[List[List[Tuple[float, float]]]],
    safe_rect: Tuple[float, float, float, float],
    input_path: str,
    preview_dir: str = PREVIEW_DIR,
) -> Tuple[str, Optional[str]]:
    """그릴 예정 경로(펜 1·2·3 구분)를 latest_preview.png로 저장하고, 이전 파일은 history/로 이동한다."""
    os.makedirs(preview_dir, exist_ok=True)
    history_dir = os.path.join(preview_dir, "history")
    latest_path = os.path.join(preview_dir, "latest_preview.png")

    archived_path: Optional[str] = None
    if os.path.exists(latest_path):
        os.makedirs(history_dir, exist_ok=True)
        ts = datetime.fromtimestamp(os.path.getmtime(latest_path)).strftime("%Y%m%d_%H%M%S")
        cand = os.path.join(history_dir, f"{ts}_preview.png")
        idx = 1
        while os.path.exists(cand):
            cand = os.path.join(history_dir, f"{ts}_{idx}_preview.png")
            idx += 1
        shutil.move(latest_path, cand)
        archived_path = cand

    r_min_x, r_max_x, r_min_y, r_max_y = safe_rect
    rect_h_mm = max(1.0, r_max_x - r_min_x)
    rect_w_mm = max(1.0, r_max_y - r_min_y)

    max_canvas_inner = 720
    pad_side = 40
    pad_top = 60
    scale = max_canvas_inner / max(rect_w_mm, rect_h_mm)
    inner_w = max(100, int(round(rect_w_mm * scale)))
    inner_h = max(100, int(round(rect_h_mm * scale)))
    canvas_w = inner_w + pad_side * 2
    canvas_h = inner_h + pad_top + pad_side

    canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)
    cv2.rectangle(
        canvas,
        (pad_side, pad_top),
        (pad_side + inner_w, pad_top + inner_h),
        (190, 190, 190),
        1,
    )

    pen_colors = [
        (200, 70, 20),   # 펜 1 (파랑)
        (40, 40, 220),   # 펜 2 (빨강)
        (40, 155, 40),   # 펜 3 (초록)
        (20, 20, 20),    # 펜 4 (검정 - 캘리그라피)
    ]
    for idx, strokes in enumerate(pen_groups):
        color = pen_colors[idx % len(pen_colors)]
        for st in strokes:
            if len(st) < 2:
                continue
            pts_px = [
                (
                    int(round(pad_side + (r_max_y - y_mm) * scale)),
                    int(round(pad_top + (r_max_x - x_mm) * scale)),
                )
                for x_mm, y_mm in st
            ]
            pts_np = np.array(pts_px, dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(canvas, [pts_np], isClosed=False, color=color, thickness=2, lineType=cv2.LINE_AA)

    header = (
        f"{os.path.basename(input_path)} | "
        f"Pen1(B):{len(pen_groups[0])}  Pen2(R):{len(pen_groups[1])}  Pen3(G):{len(pen_groups[2])}"
    )
    cv2.putText(canvas, header, (pad_side, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 40, 40), 1, cv2.LINE_AA)
    cv2.imwrite(latest_path, canvas)
    return latest_path, archived_path


def sort_strokes_nearest(strokes: List[List[Tuple[float, float]]]) -> List[List[Tuple[float, float]]]:
    """현재 펜 끝점에서 가장 가까운 다음 획(필요 시 역방향)을 선택해 공중 이동을 최소화한다."""
    if len(strokes) <= 1:
        return strokes
    remaining = [list(st) for st in strokes]
    ordered = [remaining.pop(0)]
    while remaining:
        cx, cy = ordered[-1][-1]
        best_idx, best_rev, best_d = 0, False, float("inf")
        for i, st in enumerate(remaining):
            d_start = math.hypot(st[0][0] - cx, st[0][1] - cy)
            d_end = math.hypot(st[-1][0] - cx, st[-1][1] - cy)
            if d_start < best_d:
                best_idx, best_rev, best_d = i, False, d_start
            if d_end < best_d:
                best_idx, best_rev, best_d = i, True, d_end
        nxt = remaining.pop(best_idx)
        if best_rev:
            nxt.reverse()
        ordered.append(nxt)
    return ordered


# =============================================================================
# 3. 캘리브레이션 영역 매핑 및 3개 펜 분배
# =============================================================================
def _load_json(path: str, label: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{label} 파일이 없습니다: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_safe_rect(cal: Dict, margin_mm: float = RECT_MARGIN_MM) -> Tuple[float, float, float, float]:
    pts = cal.get("points", [])
    if len(pts) < 4:
        raise ValueError("직사각형 영역을 계산할 캘리브레이션 점이 부족합니다.")
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    min_x, max_x = min(xs) + margin_mm, max(xs) - margin_mm
    min_y, max_y = min(ys) + margin_mm, max(ys) - margin_mm
    if min_x >= max_x or min_y >= max_y:
        raise ValueError("여백 적용 후 그리기 영역이 유효하지 않습니다.")
    return min_x, max_x, min_y, max_y


def fit_strokes_to_rect(
    strokes_px: List[List[Tuple[float, float]]],
    safe_rect: Tuple[float, float, float, float],
) -> List[List[Tuple[float, float]]]:
    """픽셀 획 리스트를 9점 안전 직사각형 안에 비율을 유지해 중앙 배치한다."""
    all_x = [p[0] for st in strokes_px for p in st]
    all_y = [p[1] for st in strokes_px for p in st]
    px_min_x, px_max_x = min(all_x), max(all_x)
    px_min_y, px_max_y = min(all_y), max(all_y)
    img_w = max(1.0, px_max_x - px_min_x)
    img_h = max(1.0, px_max_y - px_min_y)
    px_cx = 0.5 * (px_min_x + px_max_x)
    px_cy = 0.5 * (px_min_y + px_max_y)

    r_min_x, r_max_x, r_min_y, r_max_y = safe_rect
    rect_cx = 0.5 * (r_min_x + r_max_x)
    rect_cy = 0.5 * (r_min_y + r_max_y)
    scale = min((r_max_x - r_min_x) / img_h, (r_max_y - r_min_y) / img_w)

    return [
        [(rect_cx + (px_cy - y_px) * scale, rect_cy - (x_px - px_cx) * scale) for x_px, y_px in st]
        for st in strokes_px
    ]


def split_strokes_evenly(
    strokes: List[List[Tuple[float, float]]],
    num_parts: int = 3,
) -> List[List[List[Tuple[float, float]]]]:
    """총 점 개수가 균등해지도록 획 리스트를 3개 펜에 분배한다."""
    total_pts = sum(len(st) for st in strokes)
    target = total_pts / num_parts
    groups: List[List[List[Tuple[float, float]]]] = [[] for _ in range(num_parts)]
    g_idx, acc = 0, 0
    for st in strokes:
        if g_idx < num_parts - 1 and acc >= target * (g_idx + 1):
            g_idx += 1
        groups[g_idx].append(st)
        acc += len(st)
    return groups


# =============================================================================
# 4. 두산 로봇 제어 및 드로잉 실행
# =============================================================================
class DrawingAborted(Exception):
    """사용자 중단 요청('x' 입력 등) 시 안전 복귀를 트리거하기 위한 예외."""


def run_robot_drawing(
    pen_groups: List[List[List[Tuple[float, float]]]],
    stick_pose: List[float],
    pen_poses: List[List[float]],
    cal_points: List[List[float]],
    slope_a: float,
    slope_b: float,
    virtual: bool = False,
    auto_calibrate: bool = AUTO_CALIBRATE_9PT,
) -> None:
    import rclpy
    import DR_init

    DR_init.__dsr__id = ROBOT_ID
    DR_init.__dsr__model = ROBOT_MODEL

    rclpy.init(args=None)
    node = rclpy.create_node("draw_image_standalone", namespace=ROBOT_ID)
    DR_init.__dsr__node = node

    try:
        from DSR_ROBOT2 import (
            set_tool,
            set_tcp,
            movej,
            movel,
            movesx,
            get_current_posx,
            get_tool_force,
            set_digital_output,
            DR_MV_MOD_ABS,
            DR_MV_MOD_REL,
            DR_MVS_VEL_CONST,
            DR_BASE,
        )
        from DR_common2 import posx, posj
    except ImportError as e:
        node.get_logger().error(f"Error importing DSR_ROBOT2: {e}")
        raise

    abort_event = threading.Event()
    stop_listener_event = threading.Event()
    held_item: Optional[Tuple[List[float], str]] = None

    def check_abort() -> None:
        if abort_event.is_set():
            raise DrawingAborted("사용자 중단 요청으로 안전 복귀를 시작합니다.")

    def _keyboard_abort_listener() -> None:
        if not sys.stdin or not sys.stdin.isatty():
            return
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not stop_listener_event.is_set() and not abort_event.is_set():
                rlist, _, _ = select.select([fd], [], [], 0.1)
                if rlist:
                    ch = sys.stdin.read(1)
                    if ch.lower() == "x":
                        abort_event.set()
                        node.get_logger().warn(
                            "[중단 요청] 'x' 입력 감지 — 현재 동작 완료 후 원위치 및 홈으로 복귀합니다."
                        )
                        break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def set_gripper(pin1: int, pin2: int, label: str) -> None:
        set_digital_output(1, OFF)
        set_digital_output(2, OFF)
        if pin1 != OFF or pin2 != OFF:
            set_digital_output(1, pin1)
            set_digital_output(2, pin2)
        time.sleep(0.5)
        node.get_logger().info(f"그리퍼: {label}")

    def pick_from_slot(slot_pose: List[float], name: str) -> None:
        nonlocal held_item
        check_abort()
        x, y, z, rx, ry, rz = slot_pose
        approach = posx([x, y, z + APPROACH_OFFSET_Z, rx, ry, rz])
        target = posx([x, y, z, rx, ry, rz])
        node.get_logger().info(f"[{name}] 집기 시작")
        set_gripper(OFF, ON, "열기")
        movel(approach, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
        movel(target, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
        set_gripper(ON, OFF, "잡기")
        held_item = (list(slot_pose), name)
        movel(approach, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)

    def return_to_slot(slot_pose: List[float], name: str) -> None:
        nonlocal held_item
        x, y, z, rx, ry, rz = slot_pose
        approach = posx([x, y, z + APPROACH_OFFSET_Z, rx, ry, rz])
        target = posx([x, y, z, rx, ry, rz])
        node.get_logger().info(f"[{name}] 원위치 시작")
        movel(approach, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
        movel(target, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
        set_gripper(OFF, ON, "놓기")
        held_item = None
        movel(approach, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)

    def read_fz_avg(samples: int = READ_SAMPLES) -> float:
        vals = []
        for i in range(samples):
            val = float(get_tool_force(DR_BASE)[2])
            if not math.isfinite(val):
                raise RuntimeError("Fz 센서 측정값이 유효하지 않습니다.")
            vals.append(val)
            if i < samples - 1:
                time.sleep(SAMPLE_INTERVAL_S)
        return sum(vals) / len(vals)

    def probe_floor_contact(max_travel_mm: float, label: str) -> List[float]:
        """현재 위치에서 -Z로 조금씩 하강하며 포스 접촉 바닥 pose를 반환한다."""
        base_samples = [read_fz_avg(1) for _ in range(BASELINE_SAMPLES)]
        baseline_fz = sum(base_samples) / len(base_samples)
        if (max(base_samples) - min(base_samples)) >= CONTACT_FORCE_DELTA_N:
            raise RuntimeError(f"[{label}] 센서 노이즈가 접촉 판정 기준 이상입니다.")

        descended, step_idx, hits, probe_baseline = 0.0, 0, 0, None
        fine_mode = False
        while descended + 1e-9 < max_travel_mm:
            check_abort()
            cur_step = PROBE_FINE_STEP_MM if fine_mode else PROBE_STEP_MM
            step = min(cur_step, max_travel_mm - descended)
            movel([0.0, 0.0, -step, 0.0, 0.0, 0.0], vel=PROBE_VEL, acc=PROBE_ACC, mod=DR_MV_MOD_REL)
            descended += step
            step_idx += 1
            time.sleep(SETTLE_TIME_S)
            cur_fz = read_fz_avg()

            if CONTACT_SIGN * (cur_fz - baseline_fz) >= HARD_LIMIT_FORCE_N:
                raise RuntimeError(f"[{label}] 탐색 중 과압 감지로 중단합니다.")
            if step_idx <= WARMUP_STEPS:
                if step_idx == WARMUP_STEPS:
                    probe_baseline = cur_fz
                continue

            delta = CONTACT_SIGN * (cur_fz - probe_baseline)
            if delta >= HARD_LIMIT_FORCE_N:
                raise RuntimeError(f"[{label}] 탐색 중 과압 감지로 중단합니다. (dFz={delta:.2f} N)")
            if delta >= CONTACT_FORCE_DELTA_N:
                # 첫 접촉 감지 이후에는 정밀 탐색(0.1 mm) 모드로 전환해 과압 스파이크를 방지한다.
                fine_mode = True
                hits += 1
                if hits >= CONFIRM_COUNT:
                    contact_pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
                    node.get_logger().info(f"[{label}] 접촉 Z={contact_pose[2]:.2f} mm (dFz={delta:.2f} N)")
                    return contact_pose
            else:
                hits = 0
        raise RuntimeError(f"[{label}] 최대 하강 거리({max_travel_mm:.1f} mm) 내 접촉 미감지")

    def calibrate_9pt_with_closed_gripper(points: List[List[float]]) -> Tuple[float, float]:
        """닫힌 빈 그리퍼로 9개 XY 지점(무게추 회피를 위해 안쪽으로 CALIBRATE_INSET_MM 이동)의 Z를 재측정한다."""
        node.get_logger().info(f"=== 빈 그리퍼 9점 자동 평면 캘리브레이션 시작 (안쪽 여백 {CALIBRATE_INSET_MM:.0f} mm) ===")
        set_gripper(ON, OFF, "빈 그리퍼 닫기")

        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        cx = 0.5 * (min(xs) + max(xs))
        cy = 0.5 * (min(ys) + max(ys))

        measured_xyz: List[Tuple[float, float, float]] = []
        last_z: Optional[float] = None

        for idx, pt in enumerate(points, start=1):
            check_abort()
            x, y, z, rx, ry, rz = [float(v) for v in pt[:6]]
            if x < cx - 10.0:
                x += CALIBRATE_INSET_MM
            elif x > cx + 10.0:
                x -= CALIBRATE_INSET_MM
            if y < cy - 10.0:
                y += CALIBRATE_INSET_MM
            elif y > cy + 10.0:
                y -= CALIBRATE_INSET_MM

            start_z = (last_z + 10.0) if last_z is not None else (z + GRIPPER_PROBE_START_OFFSET_Z)
            transit_z = start_z + 30.0
            travel = 20.0 if last_z is not None else GRIPPER_PROBE_MAX_TRAVEL_MM

            movel(posx([x, y, transit_z, rx, ry, rz]), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
            movel(posx([x, y, start_z, rx, ry, rz]), vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
            contact = probe_floor_contact(travel, f"9점-{idx}/9")
            last_z = contact[2]
            measured_xyz.append((x, y, last_z))
            movel(posx([x, y, transit_z, rx, ry, rz]), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)

        arr = np.array(measured_xyz, dtype=np.float64)
        A = np.column_stack([arr[:, 0], arr[:, 1], np.ones(len(arr))])
        a_new, b_new, c_new = np.linalg.lstsq(A, arr[:, 2], rcond=None)[0]
        node.get_logger().info(f"=== 9점 캘리브레이션 완료: a={a_new:.6f}, b={b_new:.6f}, c={c_new:.2f} ===")
        return float(a_new), float(b_new)

    def measure_floor_height_with_stick() -> List[float]:
        check_abort()
        movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
        check_abort()
        movel(posx(READY_OFFSET), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
        contact_pose = probe_floor_contact(PROBE_MAX_TRAVEL_MM, "기준 막대")
        movel([0.0, 0.0, APPROACH_OFFSET_Z, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
        return contact_pose

    def draw_stroke_group(pen_name: str, strokes: List[List[Tuple[float, float]]], contact_pose: List[float], z_offset: float) -> None:
        if not strokes:
            node.get_logger().info(f"[{pen_name}] 할당된 획 없음")
            return
        bx, by, contact_z, rx, ry, rz = contact_pose

        def calc_z(ax: float, ay: float) -> float:
            return contact_z + slope_a * (ax - bx) + slope_b * (ay - by) + z_offset

        def split_at_corners(pts: List[Tuple[float, float]]) -> List[List[Tuple[float, float]]]:
            """꺾이는 각도가 CORNER_ANGLE_DEG 이상인 꼭짓점에서 획을 분할한다."""
            if len(pts) < 3:
                return [pts]
            segments: List[List[Tuple[float, float]]] = []
            cur_seg: List[Tuple[float, float]] = [pts[0], pts[1]]
            for i in range(1, len(pts) - 1):
                v1x, v1y = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
                v2x, v2y = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
                n1 = math.hypot(v1x, v1y)
                n2 = math.hypot(v2x, v2y)
                is_corner = False
                if n1 > 1e-6 and n2 > 1e-6:
                    cos_val = max(-1.0, min(1.0, (v1x * v2x + v1y * v2y) / (n1 * n2)))
                    angle_deg = math.degrees(math.acos(cos_val))
                    if angle_deg >= CORNER_ANGLE_DEG:
                        is_corner = True
                if is_corner:
                    segments.append(cur_seg)
                    cur_seg = [pts[i], pts[i + 1]]
                else:
                    cur_seg.append(pts[i + 1])
            segments.append(cur_seg)
            return segments

        check_abort()
        sx0, sy0 = strokes[0][0]
        movel(posx([sx0, sy0, calc_z(sx0, sy0) + STROKE_LIFT_MM, rx, ry, rz]), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)

        for s_idx, pts in enumerate(strokes, start=1):
            check_abort()
            sx, sy = pts[0]
            sz = calc_z(sx, sy)
            movel(posx([sx, sy, sz + IMAGE_STROKE_LIFT_MM, rx, ry, rz]), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
            movel(posx([sx, sy, sz, rx, ry, rz]), vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)

            for seg in split_at_corners(pts):
                check_abort()
                if len(seg) <= 2:
                    for x, y in seg[1:]:
                        movel(posx([x, y, calc_z(x, y), rx, ry, rz]), vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_ABS)
                else:
                    # 완만한 곡선 구간은 movesx로 연속 이동 (최대 MOVESX_MAX_POINTS 단위 분할)
                    targets = seg[1:]
                    for start in range(0, len(targets), MOVESX_MAX_POINTS):
                        check_abort()
                        chunk = targets[start : start + MOVESX_MAX_POINTS]
                        if len(chunk) == 1:
                            x, y = chunk[0]
                            movel(posx([x, y, calc_z(x, y), rx, ry, rz]), vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_ABS)
                        else:
                            pos_list = [posx([x, y, calc_z(x, y), rx, ry, rz]) for x, y in chunk]
                            movesx(
                                pos_list,
                                vel=DRAW_VEL,
                                acc=DRAW_ACC,
                                mod=DR_MV_MOD_ABS,
                                vel_opt=DR_MVS_VEL_CONST,
                            )

            ex, ey = pts[-1]
            movel(posx([ex, ey, calc_z(ex, ey) + IMAGE_STROKE_LIFT_MM, rx, ry, rz]), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
            if s_idx % 20 == 0 or s_idx == len(strokes):
                node.get_logger().info(f"[{pen_name}] 진행 {s_idx}/{len(strokes)} 획")

        ex_last, ey_last = strokes[-1][-1]
        movel(posx([ex_last, ey_last, calc_z(ex_last, ey_last) + STROKE_LIFT_MM, rx, ry, rz]), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)

    stick_grip_pose = [
        stick_pose[0],
        stick_pose[1],
        stick_pose[2],
        stick_pose[3],
        stick_pose[4],
        stick_pose[5] + STICK_GRIP_RZ_OFFSET_DEG,
    ]
    listener_thread = threading.Thread(target=_keyboard_abort_listener, daemon=True)
    listener_thread.start()
    node.get_logger().info("실행 중 'x'를 누르면 잡고 있던 펜/막대를 원위치한 뒤 홈으로 복귀합니다.")

    try:
        import DSR_ROBOT2 as _dsr
        if hasattr(_dsr, "_ros2_move_joint"):
            node.get_logger().info("로봇 서비스(/dsr01/dsr_controller2) 연결 대기 중...")
            if not _dsr._ros2_move_joint.wait_for_service(timeout_sec=15.0):
                raise RuntimeError("로봇 모션 서비스에 연결할 수 없습니다. sodreal 상태를 확인하세요.")
        if virtual:
            node.get_logger().info("[가상 모드] set_tool/set_tcp 생략 후 홈 위치로 이동합니다.")
        else:
            if hasattr(_dsr, "_ros2_set_current_tool") and not _dsr._ros2_set_current_tool.wait_for_service(timeout_sec=15.0):
                raise RuntimeError("로봇 툴 서비스에 연결할 수 없습니다. sodreal 상태를 확인하세요.")
            node.get_logger().info(f"툴/TCP 설정 중: {TOOL_NAME}, {TCP_NAME}")
            set_tool(TOOL_NAME)
            set_tcp(TCP_NAME)

        set_gripper(OFF, ON, "초기 재정렬 - 열기")
        set_gripper(ON, OFF, "초기 재정렬 - 닫기")
        check_abort()

        node.get_logger().info("홈 위치 이동 시작...")
        movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
        node.get_logger().info("홈 위치 도착 완료")
        check_abort()

        if virtual:
            node.get_logger().info("[가상 모드] 9점/기준막대 포스 탐색 생략 -> plane_calibration.json 좌표 사용")
            pick_from_slot(stick_grip_pose, "기준 막대(가상)")
            contact_pose = [float(v) for v in cal_points[0][:6]]
            return_to_slot(stick_grip_pose, "기준 막대(가상)")
        else:
            if auto_calibrate:
                slope_a, slope_b = calibrate_9pt_with_closed_gripper(cal_points)
                movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
                check_abort()
            else:
                node.get_logger().info(
                    f"9점 자동 캘리브레이션 OFF -> 저장된 평면 기울기 사용 (a={slope_a:.6f}, b={slope_b:.6f})"
                )

            pick_from_slot(stick_grip_pose, "기준 막대")
            contact_pose = measure_floor_height_with_stick()
            return_to_slot(stick_grip_pose, "기준 막대")

        for idx, strokes in enumerate(pen_groups):
            if not strokes:
                continue
            check_abort()
            pen_name = f"펜 {idx + 1}"
            pick_from_slot(pen_poses[idx], pen_name)
            z_off = PEN_Z_OFFSETS[idx] if idx < len(PEN_Z_OFFSETS) else PEN_Z_OFFSETS[-1]
            draw_stroke_group(pen_name, strokes, contact_pose, z_off)
            return_to_slot(pen_poses[idx], pen_name)

        movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
        set_gripper(OFF, OFF, "기본")
        node.get_logger().info("독립 실행 멀티펜 드로잉 완료!")
    except DrawingAborted as e:
        node.get_logger().warn(str(e))
        cur_pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
        if held_item is not None:
            held_pose, held_name = held_item
            safe_z = max(cur_pose[2] + STROKE_LIFT_MM, held_pose[2] + APPROACH_OFFSET_Z)
            movel(
                posx([cur_pose[0], cur_pose[1], safe_z, cur_pose[3], cur_pose[4], cur_pose[5]]),
                vel=L_VEL,
                acc=L_ACC,
                mod=DR_MV_MOD_ABS,
            )
            return_to_slot(held_pose, held_name)
        else:
            movel(
                posx([cur_pose[0], cur_pose[1], cur_pose[2] + STROKE_LIFT_MM, cur_pose[3], cur_pose[4], cur_pose[5]]),
                vel=L_VEL,
                acc=L_ACC,
                mod=DR_MV_MOD_ABS,
            )
        movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
        set_gripper(OFF, OFF, "기본")
        node.get_logger().info("중단 후 안전 복귀 및 홈 이동 완료")
    finally:
        stop_listener_event.set()
        listener_thread.join(timeout=0.5)
        node.destroy_node()
        rclpy.shutdown()


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="단일 파일 독립 실행 멀티펜 이미지 드로잉")
    parser.add_argument("--input", default=DEFAULT_INPUT_PATH, help="입력 이미지(.png/.jpg) 또는 strokes JSON 경로")
    parser.add_argument("--dry-run", action="store_true", help="로봇 이동 없이 변환/배치/분배 결과만 출력")
    parser.add_argument("--virtual", action="store_true", help="sodvir 가상 모드용 (포스 탐색 생략 후 저장된 평면 높이로 시뮬레이션)")
    cal_group = parser.add_mutually_exclusive_group()
    cal_group.add_argument("--skip-cal", "--no-cal", action="store_true", help="9점 자동 캘리브레이션 OFF (건너뛰기)")
    cal_group.add_argument("--cal", action="store_true", help="9점 자동 캘리브레이션 ON (강제 실행)")
    args, _ = parser.parse_known_args(argv)

    auto_calibrate = AUTO_CALIBRATE_9PT
    if args.skip_cal:
        auto_calibrate = False
    elif args.cal:
        auto_calibrate = True

    stick_pose = [float(v) for v in _load_json(STICK_FILE, "기준 막대 위치")[:6]]
    pen_data = _load_json(PENS_FILE, "펜 위치")
    if len(pen_data) not in (3, 4):
        raise ValueError(f"펜 위치 개수가 3개 또는 4개가 아닙니다: {PENS_FILE}")
    pen_poses = [[float(v) for v in p[:6]] for p in pen_data]

    cal = _load_json(CALIBRATION_FILE, "9점 캘리브레이션")
    cal_points = cal.get("points", [])
    slope_a, slope_b = float(cal.get("a", 0.0)), float(cal.get("b", 0.0))
    safe_rect = compute_safe_rect(cal, RECT_MARGIN_MM)

    strokes_px = load_strokes_from_input(args.input)
    strokes_mm = fit_strokes_to_rect(strokes_px, safe_rect)

    pen_ids = None
    if args.input.lower().endswith(".json"):
        with open(args.input, "r", encoding="utf-8") as f:
            pen_ids = json.load(f).get("pen_ids")

    if isinstance(pen_ids, list) and len(pen_ids) == len(strokes_mm) and "PEN_4" in pen_ids:
        art_strokes = [st for st, pid in zip(strokes_mm, pen_ids) if pid != "PEN_4"]
        text_strokes = [st for st, pid in zip(strokes_mm, pen_ids) if pid == "PEN_4"]
        art_groups = split_strokes_evenly(art_strokes, num_parts=3) if art_strokes else [[], [], []]
        if SORT_NEAREST_STROKES:
            art_groups = [sort_strokes_nearest(g) for g in art_groups]
        if len(pen_poses) < 4:
            raise ValueError(f"4번째 펜(검은색 글씨용) 슬롯 좌표가 없습니다. {PENS_FILE}에 4번째 좌표를 추가하세요.")
        pen_groups = art_groups + [text_strokes]
    else:
        pen_groups = split_strokes_evenly(strokes_mm, num_parts=3)
        if SORT_NEAREST_STROKES:
            pen_groups = [sort_strokes_nearest(g) for g in pen_groups]

    preview_path, archived_path = save_drawing_preview(pen_groups, safe_rect, args.input)
    print(
        f"[준비 완료] 입력={args.input} | 총 획={len(strokes_mm)}개 | "
        f"펜별 분배={[len(g) for g in pen_groups]} | "
        f"9점캘리브레이션={'ON' if auto_calibrate else 'OFF'} | "
        f"영역 X=[{safe_rect[0]:.1f}~{safe_rect[1]:.1f}], Y=[{safe_rect[2]:.1f}~{safe_rect[3]:.1f}]"
    )
    print(f"[미리보기 저장] {preview_path}" + (f" (이전 파일 백업: {archived_path})" if archived_path else ""))
    if args.dry_run:
        return

    run_robot_drawing(
        pen_groups,
        stick_pose,
        pen_poses,
        cal_points,
        slope_a,
        slope_b,
        virtual=args.virtual,
        auto_calibrate=auto_calibrate,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
