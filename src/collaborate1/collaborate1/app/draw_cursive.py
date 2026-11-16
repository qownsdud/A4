"""모든 알파벳 필기체(두께 2mm~3mm 변화) 그리기 노드.

draw1.py의 파라미터와 막대기 높이 조절 로직을 그대로 유지하고,
cursive_font.py를 이용해 임의의 알파벳 문자열을 3D(X, Y, Z굵기) 필기체로 그린다.
"""

# 글을 쓰는 중에 멈추지 않도록 등속설정 무브b

import json
import math
import os
import time
import rclpy
import DR_init

from collaborate1.core.cursive_font import text_to_strokes
from collaborate1.core.run_logger import RunLogSession

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"

# --- 속도 / 가속도 설정 ---
J_VEL, J_ACC = 60, 60            # Joint 이동 (deg/s, deg/s^2)
L_VEL, L_ACC = 50, 50          # 일반 Linear 공중 이동 (mm/s, mm/s^2)
PROBE_VEL, PROBE_ACC = 5, 5      # 막대기 접촉 탐색 속도 (mm/s, mm/s^2)
START_DOWN_VEL, START_DOWN_ACC = 40, 40  # 획 시작점 진입 하강 속도 (mm/s, mm/s^2)
DRAW_VEL, DRAW_ACC = 500, 500      # 필기체 그리기 속도 (mm/s, mm/s^2)

# --- 시작 위치 설정 (draw1.py 그대로 유지) ---
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

# --- 2단계: 필기체 두께(높이) 설정 ---
THICK_LIFT_MM = 2.0              # 굵은 획(내려긋기): 접촉 높이 + 2.0 mm
THIN_LIFT_MM = 3.0               # 얇은 획(올려긋기): 접촉 높이 + 3.0 mm

# --- 3단계: 필기체 텍스트 및 리프트 설정 ---
DEFAULT_TEXT = "Hello"           # 기본 쓸 문구 (A-Z, a-z, 공백 지원)
DEFAULT_CHAR_HEIGHT_MM = 16.0    # 소문자 x-height 기준 크기 (mm)
STROKE_LIFT_MM = 5.0             # 획 전환 시 공중 이동 높이 (mm)
END_LIFT_MM = 30.0               # 완료 후 들어올릴 높이 (mm)
MAX_MOVESX_POINTS = 80           # movesx 1회 호출당 최대 경유점 수
CALIBRATION_FILE = os.path.expanduser("~/.ros/plane_calibration.json")

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init(args=None)
node = rclpy.create_node("draw_cursive", namespace=ROBOT_ID)
node.declare_parameter("text", DEFAULT_TEXT)
node.declare_parameter("char_height_mm", DEFAULT_CHAR_HEIGHT_MM)
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
        raise RuntimeError(f"센서 노이즈({noise:.3f} N)가 접촉 판정 기준 이상입니다.")
    return baseline


def get_contact_base_pose(baseline_fz: float) -> list[float]:
    """막대기가 바닥에 닿을 때까지 하강 후 접촉 기준 pose를 반환한다."""
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

        if CONTACT_SIGN * (cur_fz - baseline_fz) >= HARD_LIMIT_FORCE_N:
            raise RuntimeError("탐색 중 과압 감지로 중단합니다.")

        if step_idx <= WARMUP_STEPS:
            if step_idx == WARMUP_STEPS:
                probe_baseline = cur_fz
                node.get_logger().info(f"[1단계] 하강 기준값 설정: {probe_baseline:.3f} N")
            continue

        delta = CONTACT_SIGN * (cur_fz - probe_baseline)
        node.get_logger().info(f"하강 {descended:.2f}/{PROBE_MAX_TRAVEL_MM:.2f} mm | deltaFz={delta:+.3f} N")
        if delta >= HARD_LIMIT_FORCE_N:
            raise RuntimeError("탐색 중 과압 감지로 중단합니다.")

        if delta >= CONTACT_FORCE_DELTA_N:
            hits += 1
            if hits >= CONFIRM_COUNT:
                contact_pose = list(get_current_posx(DR_BASE)[0][:6])
                node.get_logger().info(
                    f"[1단계 완료] 접촉 Z={contact_pose[2]:.2f} mm (굵은=+{THICK_LIFT_MM}mm, 얇은=+{THIN_LIFT_MM}mm)"
                )
                return contact_pose
        else:
            hits = 0

    raise RuntimeError("최대 하강 거리 내에서 막대기 접촉을 감지하지 못했습니다.")


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


def draw_cursive_text(text: str, char_height_mm: float, contact_pose: list[float]) -> None:
    """문자열을 3D 필기체(X, Y + 두께 Z + 바닥 기울기 보정)로 변환하여 그린다."""
    bx, by, contact_z, rx, ry, rz = contact_pose
    slope_a, slope_b = load_plane_slope()
    strokes = text_to_strokes(
        text,
        char_height_mm=char_height_mm,
        thick_z_mm=THICK_LIFT_MM,
        thin_z_mm=THIN_LIFT_MM,
        steps_per_seg=2,
    )
    if not strokes:
        raise ValueError(f"그릴 수 있는 알파벳이 없습니다: {text!r}")

    node.get_logger().info(f"[2단계] 필기체 '{text}' 시작 (총 {len(strokes)}획, 높이={char_height_mm} mm)")

    # 첫 획 진입 전 안전 높이 상승
    movel([0.0, 0.0, STROKE_LIFT_MM + THIN_LIFT_MM, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

    for s_idx, pts in enumerate(strokes, start=1):
        sx, sy, sz_off = pts[0]
        start_z = contact_z + slope_a * sx + slope_b * sy + sz_off
        start_hover_z = contact_z + slope_a * sx + slope_b * sy + THIN_LIFT_MM + STROKE_LIFT_MM

        # 시작점 위 공중으로 이동 -> 시작점 하강
        movel(posx([bx + sx, by + sy, start_hover_z, rx, ry, rz]),
              vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
        movel(posx([bx + sx, by + sy, start_z, rx, ry, rz]),
              vel=START_DOWN_VEL, acc=START_DOWN_ACC, mod=DR_MV_MOD_ABS)

        # 보조 직선 획(점 2개)은 movel, 곡선 획은 movesx(최대 경유점 분할)로 이동
        waypoints = [
            posx([bx + x, by + y, contact_z + slope_a * x + slope_b * y + z_off, rx, ry, rz])
            for x, y, z_off in pts[1:]
        ]
        if len(waypoints) <= 1:
            for wp in waypoints:
                movel(wp, vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_ABS)
        else:
            for i in range(0, len(waypoints), MAX_MOVESX_POINTS):
                chunk = waypoints[i : i + MAX_MOVESX_POINTS]
                if len(chunk) == 1:
                    movel(chunk[0], vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_ABS)
                else:
                    movesx(chunk, vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_ABS)

        ex, ey, _ = pts[-1]
        end_hover_z = contact_z + slope_a * ex + slope_b * ey + THIN_LIFT_MM + STROKE_LIFT_MM
        movel(posx([bx + ex, by + ey, end_hover_z, rx, ry, rz]),
              vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
        node.get_logger().info(f"[2단계] 획 {s_idx}/{len(strokes)} 완료 ({len(pts)}점)")


def main() -> None:
    with RunLogSession("draw_cursive"):
        try:
            text = str(node.get_parameter("text").value)
            char_height_mm = float(node.get_parameter("char_height_mm").value)

            set_tool(TOOL_NAME)
            set_tcp(TCP_NAME)

            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
            movel(posx(READY_OFFSET), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

            baseline_fz = measure_baseline()
            contact_pose = get_contact_base_pose(baseline_fz)
            draw_cursive_text(text, char_height_mm, contact_pose)

            movel([0.0, 0.0, END_LIFT_MM, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
            node.get_logger().info("필기체 그리기 및 홈 복귀 완료!")
        except Exception as exc:
            node.get_logger().error(f"draw_cursive 중단: {exc}")
            raise
        finally:
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
