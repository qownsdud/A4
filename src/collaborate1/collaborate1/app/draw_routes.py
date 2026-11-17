"""draw1.py 기반 복잡한 다중 루트 스무스 그리기 테스트 노드.

draw1.py의 파라미터와 막대기 높이 조절 로직을 그대로 유지하고,
3단계 그리기만 다양한 긴 루트(사인파, 지그재그, 나선, 별)로 대체했다.
"""

import json
import math
import os
import time
import rclpy
import DR_init

from collaborate1.core.run_logger import RunLogSession

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"

# --- 속도 / 가속도 설정 (draw1.py 그대로 유지) ---
J_VEL, J_ACC = 60, 60            # Joint 이동 (deg/s, deg/s^2)
L_VEL, L_ACC = 100, 100            # 일반 Linear 이동 (mm/s, mm/s^2) 50, 50
PROBE_VEL, PROBE_ACC = 10, 10      # 막대기 접촉 탐색 속도 (mm/s, mm/s^2)
DRAW_VEL, DRAW_ACC = 30, 30      # 붓펜 스무스 그리기 속도 (mm/s, mm/s^2) 15, 15

# --- 시작 위치 설정 (draw1.py 그대로 유지) ---
USE_HOME_READY = False
HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
READY_OFFSET = [0.0, 0.0, -90.0, 0.0, 0.0, 0.0]

# --- 1단계: 막대기 바닥 접촉 감지 파라미터 (draw1.py 그대로 유지) ---
PROBE_STEP_MM = 0.5              # 1회 하강 간격 (mm)
PROBE_MAX_TRAVEL_MM = 20.0       # 최대 하강 허용 거리 (mm)
WARMUP_STEPS = 2                 # 첫 하강 시 관절 마찰 오프셋 안정화용 워밍업 스텝 수
SETTLE_TIME_S = 0.12             # 각 이동 정지 후 진동 안정화 대기 시간 (s)
READ_SAMPLES = 3                 # 1회 외력 측정 시 평균낼 샘플 수
CONTACT_FORCE_DELTA_N = 2.5      # 막대기 접촉 판정 외력 변화량 (N)
HARD_LIMIT_FORCE_N = 30.0        # 과압 즉시 중단 한계 (N)
CONFIRM_COUNT = 2                # 노이즈 오판 방지용 연속 감지 횟수
BASELINE_SAMPLES = 10            # 정지 상태 기준 외력 샘플 수
SAMPLE_INTERVAL_S = 0.03         # 샘플링 주기 (s)
CONTACT_SIGN = +1                # 바닥 반력 Fz가 증가하면 +1, 감소하면 -1

# --- 2단계: 막대기 접촉 후 붓펜 굵기별 높이 조절 파라미터 ---
THICK_LIFT_MM = 2.0              # 굵은 선: 막대기 접촉 높이에서 +2.0 mm 상승
THIN_LIFT_MM = 3.0               # 얇은 선: 막대기 접촉 높이에서 +3.0 mm 상승

# --- 3단계: 복잡한 루트 그리기 파라미터 ---
ENABLE_DRAWING = True
STROKE_LIFT_MM = 5.0             # 루트 간 이동 시 들어올릴 높이 (mm)
END_LIFT_MM = 30.0               # 그리기 완료 후 들어올릴 높이 (mm)
CALIBRATION_FILE = os.path.expanduser("~/.ros/plane_calibration.json")

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init(args=None)
node = rclpy.create_node("draw_routes", namespace=ROBOT_ID)
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
        DR_MV_MOD_ABS,
        DR_MV_MOD_REL,
        DR_BASE,
    )
    from DR_common2 import posx, posj
except ImportError as e:
    node.get_logger().error(f"Error importing DSR_ROBOT2: {e}")
    raise


def read_fz() -> float:
    """Base 기준 외력 Z(N)를 읽고 유효성을 검사한다."""
    val = float(get_tool_force(DR_BASE)[2])
    if not math.isfinite(val):
        raise RuntimeError("Fz 센서 측정값이 유효하지 않습니다.")
    return val


def read_fz_avg(samples: int = READ_SAMPLES) -> float:
    """짧은 간격으로 여러 번 읽어 평균낸 외력 Z(N)를 반환한다."""
    vals = []
    for i in range(samples):
        vals.append(read_fz())
        if i < samples - 1:
            time.sleep(SAMPLE_INTERVAL_S)
    return sum(vals) / len(vals)


def measure_baseline() -> float:
    """비접촉 정지 상태에서 기준 외력(Fz)과 노이즈 폭을 측정한다."""
    samples = []
    for _ in range(BASELINE_SAMPLES):
        samples.append(read_fz())
        time.sleep(SAMPLE_INTERVAL_S)
    baseline = sum(samples) / len(samples)
    noise = max(samples) - min(samples)
    node.get_logger().info(f"[초기화] Baseline Fz={baseline:.3f} N, noise={noise:.3f} N")
    if noise >= CONTACT_FORCE_DELTA_N:
        raise RuntimeError(
            f"센서 노이즈({noise:.3f} N)가 접촉 판정 기준({CONTACT_FORCE_DELTA_N} N) 이상입니다."
        )
    return baseline


def probe_stick_contact(baseline_fz: float) -> tuple[float, float]:
    """막대기가 바닥에 닿아 외력이 발생할 때까지 하강하고 멈춘다."""
    descended = 0.0
    step_idx = 0
    hits = 0
    probe_baseline = None
    node.get_logger().info("[1단계] 막대기 바닥 접촉 탐색 시작")

    while descended + 1e-9 < PROBE_MAX_TRAVEL_MM:
        step = min(PROBE_STEP_MM, PROBE_MAX_TRAVEL_MM - descended)
        movel([0.0, 0.0, -step, 0.0, 0.0, 0.0], vel=PROBE_VEL, acc=PROBE_ACC, mod=DR_MV_MOD_REL)
        descended += step
        step_idx += 1

        time.sleep(SETTLE_TIME_S)
        cur_fz = read_fz_avg()

        raw_delta = CONTACT_SIGN * (cur_fz - baseline_fz)
        if raw_delta >= HARD_LIMIT_FORCE_N:
            raise RuntimeError(
                f"과압 감지(raw deltaFz={raw_delta:+.3f} N >= {HARD_LIMIT_FORCE_N} N). 즉시 중단합니다."
            )

        if step_idx <= WARMUP_STEPS:
            node.get_logger().info(
                f"워밍업 하강 {descended:.2f} mm | Fz={cur_fz:.3f} N (초기 대비 {raw_delta:+.3f} N)"
            )
            if step_idx == WARMUP_STEPS:
                probe_baseline = cur_fz
                node.get_logger().info(
                    f"[1단계] 하강 기준값(probe_baseline) 설정: {probe_baseline:.3f} N"
                )
            continue

        delta = CONTACT_SIGN * (cur_fz - probe_baseline)
        node.get_logger().info(
            f"하강 {descended:.2f}/{PROBE_MAX_TRAVEL_MM:.2f} mm | Fz={cur_fz:.3f} N, deltaFz={delta:+.3f} N"
        )

        if delta >= HARD_LIMIT_FORCE_N:
            raise RuntimeError(
                f"과압 감지(deltaFz={delta:+.3f} N >= {HARD_LIMIT_FORCE_N} N). 즉시 중단합니다."
            )

        if delta >= CONTACT_FORCE_DELTA_N:
            hits += 1
            if hits >= CONFIRM_COUNT:
                contact_z = float(get_current_posx(DR_BASE)[0][2])
                node.get_logger().info(
                    f"[1단계 완료] 막대기 바닥 접촉 감지! 정지 Z={contact_z:.2f} mm (하강 {descended:.2f} mm)"
                )
                return contact_z, descended
        else:
            hits = 0

    raise RuntimeError(
        f"최대 하강 거리({PROBE_MAX_TRAVEL_MM} mm) 내에서 막대기 접촉을 감지하지 못했습니다."
    )


def get_contact_base_pose(baseline_fz: float) -> list[float]:
    """막대기가 바닥에 닿은 시점의 기준 pose(Z = 막대기 접촉 높이)를 반환한다."""
    probe_stick_contact(baseline_fz)
    contact_pose = list(get_current_posx(DR_BASE)[0][:6])
    node.get_logger().info(
        f"[2단계] 기준 접촉 Z={contact_pose[2]:.2f} mm "
        f"(굵은 선=+{THICK_LIFT_MM:.1f} mm, 얇은 선=+{THIN_LIFT_MM:.1f} mm)"
    )
    return contact_pose


def build_wave_route(length_mm: float = 100.0, amp_mm: float = 15.0, cycles: float = 3.0, n_pts: int = 60) -> list[tuple[float, float]]:
    """긴 사인파 물결 곡선 루트."""
    return [
        (length_mm * i / n_pts, amp_mm * math.sin(2.0 * math.pi * cycles * i / n_pts))
        for i in range(n_pts + 1)
    ]


def build_zigzag_route(length_mm: float = 100.0, amp_mm: float = 16.0, teeth: int = 5) -> list[tuple[float, float]]:
    """긴 지그재그 루트."""
    pts = [(0.0, 26.0)]
    step_x = length_mm / (teeth * 2)
    for k in range(1, teeth * 2 + 1):
        sign = 1.0 if k % 2 == 1 else -1.0
        pts.append((step_x * k, 26.0 + sign * amp_mm))
    pts.append((length_mm, 26.0))
    return pts


def build_spiral_route(cx: float = 70.0, cy: float = -28.0, max_r: float = 22.0, turns: float = 2.5, n_pts: int = 75) -> list[tuple[float, float]]:
    """원형 나선 곡선 루트."""
    pts = []
    for i in range(n_pts + 1):
        t = i / n_pts
        ang = 2.0 * math.pi * turns * t
        r = 2.0 + (max_r - 2.0) * t
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def build_star_route(cx: float = 22.0, cy: float = -28.0, outer_r: float = 22.0) -> list[tuple[float, float]]:
    """5각 별 모양 일필휘지 루트."""
    pts = []
    for k in range(6):
        ang = math.radians(90.0 + k * 144.0)
        pts.append((cx + outer_r * math.cos(ang), cy + outer_r * math.sin(ang)))
    return pts


def load_plane_slope(path: str = CALIBRATION_FILE) -> tuple[float, float]:
    """저장된 9점 캘리브레이션에서 평면 기울기 (a, b)를 불러온다."""
    if not os.path.exists(path):
        node.get_logger().info("[기울기 보정] 캘리브레이션 파일 없음 -> 보정 미적용(0, 0)")
        return 0.0, 0.0
    with open(path, "r", encoding="utf-8") as f:
        cal = json.load(f)
    a, b = float(cal.get("a", 0.0)), float(cal.get("b", 0.0))
    node.get_logger().info(f"[기울기 보정] 적용: a={a:+.6f}, b={b:+.6f}")
    return a, b


def draw_complex_routes(contact_pose: list[float]) -> None:
    """접촉 기준 높이에서 굵기별 오프셋과 바닥 기울기 보정을 적용해 그린다."""
    bx, by, contact_z, rx, ry, rz = contact_pose
    slope_a, slope_b = load_plane_slope()
    lift_by_thickness = {
        "thick": THICK_LIFT_MM,
        "thin": THIN_LIFT_MM,
    }
    routes = [
        ("1. 사인파 물결 (굵은 선)", "thick", "spline", build_wave_route()),
        ("2. 지그재그 (얇은 선)", "thin", "line", build_zigzag_route()),
        ("3. 나선 곡선 (굵은 선)", "thick", "spline", build_spiral_route()),
        ("4. 별 모양 (얇은 선)", "thin", "line", build_star_route()),
    ]

    # 첫 루트 진입 전 안전 높이로 들어올림
    movel([0.0, 0.0, STROKE_LIFT_MM + THIN_LIFT_MM, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

    for name, thickness, mode, pts in routes:
        lift = lift_by_thickness[thickness]
        sx, sy = pts[0]
        start_z = contact_z + slope_a * sx + slope_b * sy + lift
        start_hover_z = start_z + STROKE_LIFT_MM

        movel(posx([bx + sx, by + sy, start_hover_z, rx, ry, rz]),
              vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
        movel(posx([bx + sx, by + sy, start_z, rx, ry, rz]),
              vel=PROBE_VEL, acc=PROBE_ACC, mod=DR_MV_MOD_ABS)

        waypoints = [
            posx([bx + x, by + y, contact_z + slope_a * x + slope_b * y + lift, rx, ry, rz])
            for x, y in pts[1:]
        ]
        node.get_logger().info(
            f"[3단계] {name} 시작 (mode={mode}, Z={start_z:.2f} mm, {len(waypoints)}구간)"
        )
        if mode == "spline":
            movesx(waypoints, vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_ABS)
        else:
            for wp in waypoints:
                movel(wp, vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_ABS)

        ex, ey = pts[-1]
        end_hover_z = contact_z + slope_a * ex + slope_b * ey + lift + STROKE_LIFT_MM
        movel(posx([bx + ex, by + ey, end_hover_z, rx, ry, rz]),
              vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
        node.get_logger().info(f"[3단계] {name} 완료")


def main() -> None:
    with RunLogSession("draw_routes"):
        try:
            if not (0.0 < CONTACT_FORCE_DELTA_N < HARD_LIMIT_FORCE_N):
                raise ValueError("CONTACT_FORCE_DELTA_N은 0보다 크고 HARD_LIMIT_FORCE_N보다 작아야 합니다.")
            if not (0.0 < PROBE_STEP_MM <= PROBE_MAX_TRAVEL_MM):
                raise ValueError("PROBE_STEP_MM과 PROBE_MAX_TRAVEL_MM 설정을 확인하세요.")
            if THICK_LIFT_MM < 0.0 or THIN_LIFT_MM < 0.0:
                raise ValueError("THICK_LIFT_MM과 THIN_LIFT_MM은 0 이상이어야 합니다.")

            set_tool(TOOL_NAME)
            set_tcp(TCP_NAME)

            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
            movel(posx(READY_OFFSET), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

            baseline_fz = measure_baseline()
            contact_pose = get_contact_base_pose(baseline_fz)

            if ENABLE_DRAWING:
                draw_complex_routes(contact_pose)
            else:
                node.get_logger().info("ENABLE_DRAWING=False: 높이 조절까지만 확인하고 그리기는 생략합니다.")

            movel([0.0, 0.0, END_LIFT_MM, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
            node.get_logger().info(f"테스트 종료: 안전 높이 +{END_LIFT_MM:.1f} mm 상승 완료")

            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
        except Exception as exc:
            node.get_logger().error(f"draw_routes 중단: {exc}")
            raise
        finally:
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
