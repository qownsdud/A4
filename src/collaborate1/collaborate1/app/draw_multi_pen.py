"""1~14단계 통합 멀티펜 드로잉 노드.

실행 순서:
1. 홈 위치 출발
2. 기준 막대 집기 (stick_slot.json)
3. 포스 제어를 통한 바닥 높이 측정
4. 기준 막대 원위치
5~7.  첫 번째 펜 집기 -> 정사각형 그리기 -> 원위치
8~10. 두 번째 펜 집기 -> 정삼각형 그리기 -> 원위치
11~13. 세 번째 펜 집기 -> 원 그리기 -> 원위치
14. 홈 위치 도착
"""

import json
import math
import os
import time
from typing import List, Tuple
    
import rclpy
import DR_init

from collaborate1.core.run_logger import RunLogSession

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"

# --- 속도 / 가속도 설정 ---
J_VEL, J_ACC = 60, 60            # Joint 이동 (deg/s, deg/s^2)
L_VEL, L_ACC = 80, 80            # 공중 이동 (mm/s, mm/s^2)
PICK_VEL, PICK_ACC = 25, 25      # 픽앤플레이스 하강/상승 (mm/s, mm/s^2)
PROBE_VEL, PROBE_ACC = 5, 5      # 기준 막대 바닥 탐색 (mm/s, mm/s^2)
DRAW_VEL, DRAW_ACC = 25, 25      # 도형 그리기 (mm/s, mm/s^2)

# --- 홈 / 대기 및 접근 오프셋 ---
HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
READY_OFFSET = [0.0, 0.0, -100.0, 0.0, 0.0, 0.0]
APPROACH_OFFSET_Z = 100.0        # 슬롯 접근 시 위 +100 mm
STROKE_LIFT_MM = 15.0            # 그리기 진입 전후 상승 높이 (mm)

# --- 3단계: 기준 막대 포스 접촉 감지 파라미터 (draw1.py 기준) ---
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

# --- 펜 1, 2, 3별 그리기 높이 오프셋 (기준 막대 접촉 Z 대비 +mm) ---
# 굵은 선=2.0mm, 얇은 선=3.0mm 등 펜 길이/굵기 차이에 맞춰 개별 조정 가능
PEN_Z_OFFSETS = [14.0, 14.0, 14.0]

# --- 파일 경로 ---
STICK_FILE = os.path.expanduser("~/.ros/stick_slot.json")
PENS_FILE = os.path.expanduser("~/.ros/pen_slots.json")
CALIBRATION_FILE = os.path.expanduser("~/.ros/plane_calibration.json")

ON, OFF = 1, 0

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init(args=None)
node = rclpy.create_node("draw_multi_pen", namespace=ROBOT_ID)
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
        raise FileNotFoundError(
            f"기준 막대 위치 파일({path})이 없습니다. 먼저 teach_stick_slot을 실행하세요."
        )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [float(v) for v in data[:6]]


def load_pen_slots(path: str = PENS_FILE) -> List[List[float]]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"펜 위치 파일({path})이 없습니다. 먼저 teach_pen_slots를 실행하세요."
        )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if len(data) != 3:
        raise ValueError(f"펜 위치 개수가 3개가 아닙니다: {path}")
    return [[float(v) for v in p[:6]] for p in data]


def load_plane_slope(path: str = CALIBRATION_FILE) -> Tuple[float, float]:
    if not os.path.exists(path):
        node.get_logger().info("[기울기 보정] 캘리브레이션 파일 없음 -> (0, 0)")
        return 0.0, 0.0
    with open(path, "r", encoding="utf-8") as f:
        cal = json.load(f)
    a, b = float(cal.get("a", 0.0)), float(cal.get("b", 0.0))
    node.get_logger().info(f"[기울기 보정] 적용: a={a:+.6f}, b={b:+.6f}")
    return a, b


def pick_from_slot(slot_pose: List[float], name: str) -> None:
    """슬롯 위 +100 mm 접근 -> 하강 -> 집기 -> +100 mm 상승."""
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
    """슬롯 위 +100 mm 접근 -> 하강 -> 놓기 -> +100 mm 상승."""
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
    """3단계: 홈 -> READY_OFFSET 하강 후 기준 막대 포스 감지로 바닥 접촉 pose를 측정한다."""
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


def build_square(cx: float, cy: float, size_mm: float = 40.0) -> List[Tuple[float, float]]:
    h = size_mm / 2.0
    return [
        (cx - h, cy - h),
        (cx + h, cy - h),
        (cx + h, cy + h),
        (cx - h, cy + h),
        (cx - h, cy - h),
    ]


def build_triangle(cx: float, cy: float, side_mm: float = 45.0) -> List[Tuple[float, float]]:
    r = side_mm / math.sqrt(3.0)
    pts = []
    for k in range(4):
        ang = math.radians(90.0 + k * 120.0)
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def build_circle(cx: float, cy: float, radius_mm: float = 22.0, n_pts: int = 48) -> List[Tuple[float, float]]:
    return [
        (cx + radius_mm * math.cos(2.0 * math.pi * i / n_pts),
         cy + radius_mm * math.sin(2.0 * math.pi * i / n_pts))
        for i in range(n_pts + 1)
    ]


def draw_shape(
    name: str,
    mode: str,
    pts: List[Tuple[float, float]],
    contact_pose: List[float],
    z_offset: float,
    slope_a: float,
    slope_b: float,
) -> None:
    """측정된 바닥 Z와 기울기 보정을 적용해 도형(line/spline)을 그린다."""
    bx, by, contact_z, rx, ry, rz = contact_pose
    sx, sy = pts[0]
    start_z = contact_z + slope_a * sx + slope_b * sy + z_offset
    start_hover_z = start_z + STROKE_LIFT_MM

    node.get_logger().info(f"[그리기] {name} 시작 (mode={mode}, offset=+{z_offset:.1f} mm)")
    movel(posx([bx + sx, by + sy, start_hover_z, rx, ry, rz]),
          vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
    movel(posx([bx + sx, by + sy, start_z, rx, ry, rz]),
          vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)

    waypoints = [
        posx([bx + x, by + y, contact_z + slope_a * x + slope_b * y + z_offset, rx, ry, rz])
        for x, y in pts[1:]
    ]
    if mode == "spline":
        movesx(waypoints, vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_ABS)
    else:
        for wp in waypoints:
            movel(wp, vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_ABS)

    ex, ey = pts[-1]
    end_hover_z = contact_z + slope_a * ex + slope_b * ey + z_offset + STROKE_LIFT_MM
    movel(posx([bx + ex, by + ey, end_hover_z, rx, ry, rz]),
          vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
    node.get_logger().info(f"[그리기] {name} 완료")


def main() -> None:
    with RunLogSession("draw_multi_pen"):
        try:
            stick_pose = load_stick_slot()
            pen_poses = load_pen_slots()
            slope_a, slope_b = load_plane_slope()

            set_tool(TOOL_NAME)
            set_tcp(TCP_NAME)

            # 1. 홈 위치 출발
            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)

            # 2~4. 기준 막대 집기 -> 포스 높이 측정 -> 기준 막대 원위치
            pick_from_slot(stick_pose, "기준 막대")
            contact_pose = measure_floor_height_with_stick()
            return_to_slot(stick_pose, "기준 막대")

            # 5~13. 펜 1(정사각형), 펜 2(정삼각형), 펜 3(원) 순차 그리기
            tasks = [
                ("펜 1", pen_poses[0], PEN_Z_OFFSETS[0], "정사각형", "line", build_square(0.0, -65.0)),
                ("펜 2", pen_poses[1], PEN_Z_OFFSETS[1], "정삼각형", "line", build_triangle(0.0, 0.0)),
                ("펜 3", pen_poses[2], PEN_Z_OFFSETS[2], "원", "spline", build_circle(0.0, 65.0)),
            ]

            for pen_name, pen_pose, z_off, shape_name, mode, pts in tasks:
                pick_from_slot(pen_pose, pen_name)
                draw_shape(shape_name, mode, pts, contact_pose, z_off, slope_a, slope_b)
                return_to_slot(pen_pose, pen_name)

            # 14. 홈 위치 도착
            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
            set_gripper_state(OFF, OFF, "기본")
            node.get_logger().info("1~14단계 전체 작업 완료!")
        except Exception as exc:
            node.get_logger().error(f"draw_multi_pen 중단: {exc}")
            raise
        finally:
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
