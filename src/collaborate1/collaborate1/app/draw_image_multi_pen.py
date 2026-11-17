"""9점 캘리브레이션 영역 내에서 3개 펜이 벡터 이미지를 나눠 그리는 1~14단계 통합 노드.

특징:
- draw_multi_pen.py의 오프라인 검증 파라미터(READY_OFFSET=-100, PEN_Z_OFFSETS=[14,14,14] 등) 유지
- ~/.ros/plane_calibration.json의 9개 좌표로 유추되는 직사각형 안전 영역 자동 계산
- test_image_strokes.json의 경로를 직사각형 영역 안에 비율 유지 스케일링 및 중앙 배치
- 전체 획을 점/거리 기준으로 3등분하여 펜 1, 2, 3이 사이좋게 나눠 그림
"""

import json
import math
import os
import time
from typing import Dict, List, Tuple

import rclpy
import DR_init

from collaborate1.core.run_logger import RunLogSession

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"

# --- 속도 / 가속도 설정 (draw_multi_pen.py 유지) ---
J_VEL, J_ACC = 60, 60            # Joint 이동 (deg/s, deg/s^2)
L_VEL, L_ACC = 80, 80            # 공중 이동 (mm/s, mm/s^2)
PICK_VEL, PICK_ACC = 25, 25      # 픽앤플레이스 하강/상승 (mm/s, mm/s^2)
PROBE_VEL, PROBE_ACC = 5, 5      # 기준 막대 바닥 탐색 (mm/s, mm/s^2)
DRAW_VEL, DRAW_ACC = 25, 25      # 그리기 (mm/s, mm/s^2)

# --- 홈 / 대기 및 접근 오프셋 (draw_multi_pen.py 유지) ---
HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
READY_OFFSET = [0.0, 0.0, -100.0, 0.0, 0.0, 0.0]
APPROACH_OFFSET_Z = 100.0        # 슬롯 접근 시 위 +100 mm
STROKE_LIFT_MM = 15.0            # 펜 진입 전후 안전 상승 높이 (mm)
IMAGE_STROKE_LIFT_MM = 4.0       # 이미지 내부 획 전환 시 공중 이동 높이 (mm)

# --- 3단계: 기준 막대 포스 접촉 감지 파라미터 (draw_multi_pen.py 유지) ---
PROBE_STEP_MM = 0.5
PROBE_MAX_TRAVEL_MM = 20.0
WARMUP_STEPS = 2
SETTLE_TIME_S = 0.12
READ_SAMPLES = 3
SAMPLE_INTERVAL_S = 0.03
CONTACT_FORCE_DELTA_N = 2.5
HARD_LIMIT_FORCE_N = 30.0
CONFIRM_COUNT = 2
BASELINE_SAMPLES = 10
CONTACT_SIGN = +1

# --- 펜 1, 2, 3별 그리기 높이 오프셋 (draw_multi_pen.py 유지) ---
PEN_Z_OFFSETS = [13.5, 13.5, 13.5]

# --- 9점 직사각형 영역 내 안전 여백 (mm) ---
RECT_MARGIN_MM = 20.0

from ament_index_python.packages import get_package_share_directory

# --- 파일 경로 ---
STICK_FILE = os.path.expanduser("~/.ros/stick_slot.json")
PENS_FILE = os.path.expanduser("~/.ros/pen_slots.json")
CALIBRATION_FILE = os.path.expanduser("~/.ros/plane_calibration.json")


def _resolve_image_strokes_file() -> str:
    local_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "test_image",
        "test_image_strokes.json",
    )
    if os.path.exists(local_path):
        return local_path
    return os.path.join(
        get_package_share_directory("collaborate1"),
        "test_image",
        "test_image_strokes.json",
    )


IMAGE_STROKES_FILE = _resolve_image_strokes_file()

ON, OFF = 1, 0

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init(args=None)
node = rclpy.create_node("draw_image_multi_pen", namespace=ROBOT_ID)
DR_init.__dsr__node = node

try:
    from DSR_ROBOT2 import (
        set_tool,
        set_tcp,
        movej,
        movel,
        get_current_posx,
        get_tool_force,
        set_digital_output,
        DR_MV_MOD_ABS,
        DR_MV_MOD_REL,
        DR_BASE,
    )
    from DR_common2 import posx, posj
except ImportError as e:
    node.get_logger().error(f"Error importing DSR_ROBOT2: {e}")
    raise


def set_gripper_state(pin1: int, pin2: int, label: str) -> None:
    """디지털 출력 1, 2번 핀으로 그리퍼 상태를 설정한다."""
    set_digital_output(1, OFF)
    set_digital_output(2, OFF)
    if pin1 != OFF or pin2 != OFF:
        set_digital_output(1, pin1)
        set_digital_output(2, pin2)
    time.sleep(0.5)
    node.get_logger().info(f"그리퍼: {label} (DO1={pin1}, DO2={pin2})")


def load_stick_slot(path: str = STICK_FILE) -> List[float]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"기준 막대 위치 파일({path})이 없습니다.")
    with open(path, "r", encoding="utf-8") as f:
        return [float(v) for v in json.load(f)[:6]]


def load_pen_slots(path: str = PENS_FILE) -> List[List[float]]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"펜 위치 파일({path})이 없습니다.")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if len(data) != 3:
        raise ValueError(f"펜 위치 개수가 3개가 아닙니다: {path}")
    return [[float(v) for v in p[:6]] for p in data]


def load_calibration(path: str = CALIBRATION_FILE) -> Dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"9점 캘리브레이션 파일({path})이 없습니다.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_safe_rect(cal: Dict, margin_mm: float = RECT_MARGIN_MM) -> Tuple[float, float, float, float]:
    """9개 캘리브레이션 점에서 유추되는 직사각형 영역(안전 여백 제외)을 반환한다."""
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


def load_and_fit_image_strokes(
    json_path: str,
    safe_rect: Tuple[float, float, float, float],
) -> List[List[Tuple[float, float]]]:
    """벡터 JSON을 읽어 9점 직사각형 영역 안에 비율을 유지하며 스케일링·중앙 정렬한다."""
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"벡터 이미지 파일({json_path})이 없습니다.")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    strokes_px = data.get("strokes_px", [])
    if not strokes_px:
        raise ValueError("strokes_px 데이터가 비어 있습니다.")

    all_x = [p[0] for st in strokes_px for p in st]
    all_y = [p[1] for st in strokes_px for p in st]
    px_min_x, px_max_x = min(all_x), max(all_x)
    px_min_y, px_max_y = min(all_y), max(all_y)
    img_w = max(1.0, px_max_x - px_min_x)
    img_h = max(1.0, px_max_y - px_min_y)
    px_cx = 0.5 * (px_min_x + px_max_x)
    px_cy = 0.5 * (px_min_y + px_max_y)

    r_min_x, r_max_x, r_min_y, r_max_y = safe_rect
    rect_w_x = r_max_x - r_min_x
    rect_w_y = r_max_y - r_min_y
    rect_cx = 0.5 * (r_min_x + r_max_x)
    rect_cy = 0.5 * (r_min_y + r_max_y)

    # 이미지 세로(img_h) -> 로봇 X축, 이미지 가로(img_w) -> 로봇 Y축으로 맞춰 직사각형 내 최대 크기 배치
    scale = min(rect_w_x / img_h, rect_w_y / img_w)

    mapped_strokes: List[List[Tuple[float, float]]] = []
    for st in strokes_px:
        pts_abs = []
        for x_px, y_px in st:
            # 이미지 위쪽(y_px < px_cy) -> +X, 이미지 오른쪽(x_px > px_cx) -> -Y (정방향)
            rx = rect_cx + (px_cy - y_px) * scale
            ry = rect_cy - (x_px - px_cx) * scale
            pts_abs.append((rx, ry))
        mapped_strokes.append(pts_abs)

    return mapped_strokes


def split_strokes_evenly(
    strokes: List[List[Tuple[float, float]]],
    num_parts: int = 3,
) -> List[List[List[Tuple[float, float]]]]:
    """총 점 개수가 균등해지도록 획 리스트를 3개 펜에 나눠 배분한다."""
    total_pts = sum(len(st) for st in strokes)
    target_per_part = total_pts / num_parts
    groups: List[List[List[Tuple[float, float]]]] = [[] for _ in range(num_parts)]

    g_idx = 0
    acc_pts = 0
    for st in strokes:
        if g_idx < num_parts - 1 and acc_pts >= target_per_part * (g_idx + 1):
            g_idx += 1
        groups[g_idx].append(st)
        acc_pts += len(st)
    return groups


def pick_from_slot(slot_pose: List[float], name: str) -> None:
    x, y, z, rx, ry, rz = slot_pose
    approach = posx([x, y, z + APPROACH_OFFSET_Z, rx, ry, rz])
    target = posx([x, y, z, rx, ry, rz])

    node.get_logger().info(f"[{name}] 집기 시작")
    set_gripper_state(OFF, ON, "놓기(열기)")
    movel(approach, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
    movel(target, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
    set_gripper_state(ON, OFF, "잡기")
    movel(approach, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
    node.get_logger().info(f"[{name}] 집기 완료")


def return_to_slot(slot_pose: List[float], name: str) -> None:
    x, y, z, rx, ry, rz = slot_pose
    approach = posx([x, y, z + APPROACH_OFFSET_Z, rx, ry, rz])
    target = posx([x, y, z, rx, ry, rz])

    node.get_logger().info(f"[{name}] 원위치 시작")
    movel(approach, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
    movel(target, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
    set_gripper_state(OFF, ON, "놓기")
    movel(approach, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
    node.get_logger().info(f"[{name}] 원위치 완료")


def read_fz() -> float:
    val = float(get_tool_force(DR_BASE)[2])
    if not math.isfinite(val):
        raise RuntimeError("Fz 센서 측정값이 유효하지 않습니다.")
    return val


def read_fz_avg(samples: int = READ_SAMPLES) -> float:
    vals = []
    for i in range(samples):
        vals.append(read_fz())
        if i < samples - 1:
            time.sleep(SAMPLE_INTERVAL_S)
    return sum(vals) / len(vals)


def measure_baseline() -> float:
    samples = []
    for _ in range(BASELINE_SAMPLES):
        samples.append(read_fz())
        time.sleep(SAMPLE_INTERVAL_S)
    baseline = sum(samples) / len(samples)
    noise = max(samples) - min(samples)
    node.get_logger().info(f"[높이 측정] Baseline Fz={baseline:.3f} N, noise={noise:.3f} N")
    if noise >= CONTACT_FORCE_DELTA_N:
        raise RuntimeError("센서 노이즈가 접촉 판정 기준 이상입니다.")
    return baseline


def measure_floor_height_with_stick() -> List[float]:
    """홈 -> READY_OFFSET 하강 후 기준 막대 포스 감지로 바닥 접촉 pose를 측정한다."""
    movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
    movel(posx(READY_OFFSET), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

    baseline_fz = measure_baseline()
    descended = 0.0
    step_idx = 0
    hits = 0
    probe_baseline = None

    while descended + 1e-9 < PROBE_MAX_TRAVEL_MM:
        step = min(PROBE_STEP_MM, PROBE_MAX_TRAVEL_MM - descended)
        movel([0.0, 0.0, -step, 0.0, 0.0, 0.0], vel=PROBE_VEL, acc=PROBE_ACC, mod=DR_MV_MOD_REL)
        descended += step
        step_idx += 1

        time.sleep(SETTLE_TIME_S)
        cur_fz = read_fz_avg()

        if CONTACT_SIGN * (cur_fz - baseline_fz) >= HARD_LIMIT_FORCE_N:
            raise RuntimeError("탐색 중 과압 감지로 중단합니다.")

        if step_idx <= WARMUP_STEPS:
            if step_idx == WARMUP_STEPS:
                probe_baseline = cur_fz
            continue

        delta = CONTACT_SIGN * (cur_fz - probe_baseline)
        node.get_logger().info(f"막대 하강 {descended:.2f}/{PROBE_MAX_TRAVEL_MM:.2f} mm | deltaFz={delta:+.3f} N")
        if delta >= HARD_LIMIT_FORCE_N:
            raise RuntimeError("탐색 중 과압 감지로 중단합니다.")

        if delta >= CONTACT_FORCE_DELTA_N:
            hits += 1
            if hits >= CONFIRM_COUNT:
                contact_pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
                node.get_logger().info(f"[높이 측정 완료] 바닥 Z={contact_pose[2]:.2f} mm")
                movel([0.0, 0.0, APPROACH_OFFSET_Z, 0.0, 0.0, 0.0],
                      vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
                return contact_pose
        else:
            hits = 0

    raise RuntimeError("최대 하강 거리 내에서 기준 막대 접촉을 감지하지 못했습니다.")


def draw_stroke_group(
    pen_name: str,
    strokes: List[List[Tuple[float, float]]],
    contact_pose: List[float],
    z_offset: float,
    slope_a: float,
    slope_b: float,
) -> None:
    """할당된 획 그룹을 9점 기울기 보정 Z를 적용해 순서대로 그린다."""
    if not strokes:
        node.get_logger().info(f"[{pen_name}] 할당된 획이 없습니다.")
        return

    bx, by, contact_z, rx, ry, rz = contact_pose

    def calc_z(ax: float, ay: float) -> float:
        return contact_z + slope_a * (ax - bx) + slope_b * (ay - by) + z_offset

    total_pts = sum(len(s) for s in strokes)
    node.get_logger().info(f"[{pen_name}] 그리기 시작: {len(strokes)}개 획, {total_pts}개 점")

    # 첫 획 진입 전 안전 높이
    sx0, sy0 = strokes[0][0]
    movel(posx([sx0, sy0, calc_z(sx0, sy0) + STROKE_LIFT_MM, rx, ry, rz]),
          vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)

    for s_idx, pts in enumerate(strokes, start=1):
        sx, sy = pts[0]
        sz = calc_z(sx, sy)
        movel(posx([sx, sy, sz + IMAGE_STROKE_LIFT_MM, rx, ry, rz]),
              vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
        movel(posx([sx, sy, sz, rx, ry, rz]),
              vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)

        for x, y in pts[1:]:
            movel(posx([x, y, calc_z(x, y), rx, ry, rz]),
                  vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_ABS)

        ex, ey = pts[-1]
        movel(posx([ex, ey, calc_z(ex, ey) + IMAGE_STROKE_LIFT_MM, rx, ry, rz]),
              vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)

        if s_idx % 20 == 0 or s_idx == len(strokes):
            node.get_logger().info(f"[{pen_name}] 진행 {s_idx}/{len(strokes)} 획")

    ex_last, ey_last = strokes[-1][-1]
    movel(posx([ex_last, ey_last, calc_z(ex_last, ey_last) + STROKE_LIFT_MM, rx, ry, rz]),
          vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)


def main() -> None:
    with RunLogSession("draw_image_multi_pen"):
        try:
            stick_pose = load_stick_slot()
            pen_poses = load_pen_slots()
            cal = load_calibration()
            slope_a, slope_b = float(cal.get("a", 0.0)), float(cal.get("b", 0.0))

            safe_rect = compute_safe_rect(cal, RECT_MARGIN_MM)
            strokes = load_and_fit_image_strokes(IMAGE_STROKES_FILE, safe_rect)
            pen_groups = split_strokes_evenly(strokes, num_parts=3)

            node.get_logger().info(
                f"[영역] X=[{safe_rect[0]:.1f}~{safe_rect[1]:.1f}], Y=[{safe_rect[2]:.1f}~{safe_rect[3]:.1f}] | "
                f"분배={[len(g) for g in pen_groups]}획"
            )

            set_tool(TOOL_NAME)
            set_tcp(TCP_NAME)

            # 1. 홈 위치 출발
            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)

            # 2~4. 기준 막대 집기 -> 포스 높이 측정 -> 기준 막대 원위치
            pick_from_slot(stick_pose, "기준 막대")
            contact_pose = measure_floor_height_with_stick()
            return_to_slot(stick_pose, "기준 막대")

            # 5~13. 펜 1, 2, 3 순차적으로 나눠 그리기
            for idx in range(3):
                pen_name = f"펜 {idx + 1}"
                pick_from_slot(pen_poses[idx], pen_name)
                draw_stroke_group(
                    pen_name,
                    pen_groups[idx],
                    contact_pose,
                    PEN_Z_OFFSETS[idx],
                    slope_a,
                    slope_b,
                )
                return_to_slot(pen_poses[idx], pen_name)

            # 14. 홈 위치 도착
            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
            set_gripper_state(OFF, OFF, "기본")
            node.get_logger().info("3개 펜 이미지 분할 그리기 전체 완료!")
        except Exception as exc:
            node.get_logger().error(f"draw_image_multi_pen 중단: {exc}")
            raise
        finally:
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
