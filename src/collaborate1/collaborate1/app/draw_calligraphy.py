#!/usr/bin/env python3
"""홈 위치 -> 기준 막대 바닥 높이 측정 -> 1번 펜 픽업 -> 굵기 없는/있는 버전 한글 캘리그라피 -> 펜 반납 -> 홈 복귀.

draw_multi_pen.py의 기준 막대 높이 측정(stick_slot.json, PEN_Z_OFFSETS)과
그리퍼 픽앤플레이스 로직을 사용하므로 1번 펜으로 바닥 접촉 탐색을 하지 않습니다.

실행 예시:
    python3 src/collaborate1/collaborate1/experiments/draw_calligraphy.py --text "한글"
"""

import argparse
from datetime import datetime
import json
import math
import os
import re
import subprocess
import time
from typing import List

import rclpy
import DR_init

from collaborate1.core.run_logger import RunLogSession

try:
    from collaborate1.app.calligraphy_path_gen import (
        DEFAULT_FONT,
        generate_calligraphy_paths,
    )
except ImportError:
    from calligraphy_path_gen import DEFAULT_FONT, generate_calligraphy_paths

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"

# --- 속도 / 가속도 설정 (draw_image_multi_pen.py 기준) ---
J_VEL, J_ACC = 60, 60
L_VEL, L_ACC = 80, 80
PICK_VEL, PICK_ACC = 25, 25
PROBE_VEL, PROBE_ACC = 5, 5
START_DOWN_VEL, START_DOWN_ACC = 25, 25
DRAW_VEL, DRAW_ACC = 25, 25

# --- 자세 및 슬롯 파일 설정 (draw_image_multi_pen.py 기준) ---
HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
READY_OFFSET = [0.0, 0.0, -100.0, 0.0, 0.0, 0.0]
APPROACH_OFFSET_Z = 100.0
ON, OFF = 1, 0
STICK_FILE = os.path.expanduser("~/.ros/stick_slot.json")
SLOTS_FILE = os.path.expanduser("~/.ros/pen_slots.json")
CALIBRATION_FILE = os.path.expanduser("~/.ros/plane_calibration.json")

# --- 1단계: 기준 막대 바닥 접촉 감지 파라미터 ---
PROBE_STEP_MM = 0.5
PROBE_MAX_TRAVEL_MM = 20.0
WARMUP_STEPS = 2
SETTLE_TIME_S = 0.12
READ_SAMPLES = 3
CONTACT_FORCE_DELTA_N = 2.5
HARD_LIMIT_FORCE_N = 30.0
CONFIRM_COUNT = 2
BASELINE_SAMPLES = 10
SAMPLE_INTERVAL_S = 0.03
CONTACT_SIGN = +1

# --- 2단계: 1번 펜 그리기 Z 높이 설정 (기준 막대 접촉 Z 대비 +mm) ---
PEN1_BASE_Z_OFFSET = 13.5   # draw_image_multi_pen.py의 PEN_Z_OFFSETS[0] 기준
THICK_DELTA_MM = -1.0       # 굵은 획: 기준 오프셋 - 0.5 mm (하드웨어 실측값)
THIN_DELTA_MM = +0.8        # 얇은 획: 기준 오프셋 + 0.5 mm (하드웨어 실측값)
BRUSH_FONT_PATH = "/usr/share/fonts/truetype/nanum/NanumBrush.ttf"
STROKE_LIFT_MM = 15.0       # 획 전환 시 공중 이동 높이 (mm)
END_LIFT_MM = 30.0          # 완료 후 들어올릴 높이 (mm)
MAX_MOVESX_POINTS = 80      # movesx 1회 호출당 최대 경유점 수

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init(args=None)
node = rclpy.create_node("draw_calligraphy", namespace=ROBOT_ID)
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


def load_first_pen_slot(path: str = SLOTS_FILE) -> List[float]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"저장된 펜 위치 파일({path})이 없습니다. 먼저 teach_pen_slots로 위치를 저장하세요."
        )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or len(data) < 1:
        raise ValueError(f"펜 슬롯 데이터가 비어 있습니다: {path}")
    return [float(v) for v in data[0][:6]]


def pick_from_slot(slot_pose: List[float], name: str) -> None:
    """슬롯 위 +100mm 접근 -> 하강 -> 집기 -> +100mm 상승."""
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
    """슬롯 위 +100mm 접근 -> 하강 -> 놓기 -> +100mm 상승."""
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
        raise RuntimeError(f"센서 노이즈({noise:.3f} N)가 접촉 판정 기준 이상입니다.")
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
    node.get_logger().info("[1단계] 기준 막대 바닥 접촉 탐색 시작")

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
        node.get_logger().info(f"막대 하강 {descended:.2f}/{PROBE_MAX_TRAVEL_MM:.2f} mm | deltaFz={delta:+.3f} N")
        if delta >= HARD_LIMIT_FORCE_N:
            raise RuntimeError("탐색 중 과압 감지로 중단합니다.")

        if delta >= CONTACT_FORCE_DELTA_N:
            hits += 1
            if hits >= CONFIRM_COUNT:
                contact_pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
                node.get_logger().info(f"[1단계 완료] 바닥 접촉 Z={contact_pose[2]:.2f} mm")
                movel([0.0, 0.0, APPROACH_OFFSET_Z, 0.0, 0.0, 0.0],
                      vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
                return contact_pose
        else:
            hits = 0

    raise RuntimeError("최대 하강 거리 내에서 기준 막대 접촉을 감지하지 못했습니다.")


def load_plane_slope(path: str = CALIBRATION_FILE) -> tuple[float, float]:
    if not os.path.exists(path):
        node.get_logger().info("[기울기 보정] 캘리브레이션 파일 없음 -> 보정 미적용(0, 0)")
        return 0.0, 0.0
    with open(path, "r", encoding="utf-8") as f:
        cal = json.load(f)
    a, b = float(cal.get("a", 0.0)), float(cal.get("b", 0.0))
    node.get_logger().info(f"[기울기 보정] 적용: a={a:+.6f}, b={b:+.6f}")
    return a, b


def draw_calligraphy_text(
    text: str,
    font_path: str,
    width_mm: float,
    contact_pose: List[float],
    pen_z_offset: float,
    use_thickness: bool = True,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
    preview_path: str | None = None,
) -> List[List[tuple[float, float, float]]]:
    """한글 캘리그라피 경로를 생성해 3D(X, Y + 두께 Z 또는 고정 Z + 바닥 기울기 보정)로 그린다."""
    bx, by, contact_z, rx, ry, rz = contact_pose
    slope_a, slope_b = load_plane_slope()

    z_min = pen_z_offset + (THIN_DELTA_MM if use_thickness else 0.0)
    z_max = pen_z_offset + (THICK_DELTA_MM if use_thickness else 0.0)
    hover_base = max(z_min, z_max)

    strokes = generate_calligraphy_paths(
        text=text,
        font_path=font_path,
        target_width_mm=width_mm,
        z_min_press=z_min,
        z_max_press=z_max,
        preview_path=preview_path,
    )
    if preview_path and os.path.exists(preview_path):
        node.get_logger().info(f"[미리보기 저장] {preview_path}")
        try:
            subprocess.Popen(
                ["xdg-open", preview_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            node.get_logger().warning(f"미리보기 자동 열기 실패: {exc}")
    if not strokes:
        raise ValueError(f"그릴 수 있는 획이 생성되지 않았습니다: {text!r}")

    mode_str = f"굵기 조절({z_max:.1f}~{z_min:.1f}mm)" if use_thickness else f"일정 굵기({pen_z_offset:.1f}mm)"
    node.get_logger().info(
        f"[2단계] 캘리그라피 '{text}' 시작 [{mode_str}] "
        f"(총 {len(strokes)}획, 폭={width_mm} mm, 오프셋=({offset_x_mm:.1f}, {offset_y_mm:.1f}))"
    )

    for s_idx, pts in enumerate(strokes, start=1):
        sx = pts[0][0] + offset_x_mm
        sy = pts[0][1] + offset_y_mm
        sz_off = pts[0][2]
        start_z = contact_z + slope_a * sx + slope_b * sy + sz_off
        start_hover_z = contact_z + slope_a * sx + slope_b * sy + hover_base + STROKE_LIFT_MM

        movel(posx([bx + sx, by + sy, start_hover_z, rx, ry, rz]),
              vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
        movel(posx([bx + sx, by + sy, start_z, rx, ry, rz]),
              vel=START_DOWN_VEL, acc=START_DOWN_ACC, mod=DR_MV_MOD_ABS)

        waypoints = [
            posx([
                bx + x + offset_x_mm,
                by + y + offset_y_mm,
                contact_z + slope_a * (x + offset_x_mm) + slope_b * (y + offset_y_mm) + z_off,
                rx,
                ry,
                rz,
            ])
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

        ex = pts[-1][0] + offset_x_mm
        ey = pts[-1][1] + offset_y_mm
        end_hover_z = contact_z + slope_a * ex + slope_b * ey + hover_base + STROKE_LIFT_MM
        movel(posx([bx + ex, by + ey, end_hover_z, rx, ry, rz]),
              vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
        node.get_logger().info(f"[2단계] 획 {s_idx}/{len(strokes)} 완료 ({len(pts)}점)")

    return strokes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="홈 -> 기준 막대 높이 측정 -> 1번 펜 픽업 -> 굵기 없는/있는 버전 -> 펜 반납 -> 홈 복귀"
    )
    parser.add_argument("--text", default="한글", help="그릴 문구 (기본값: 한글)")
    parser.add_argument("--font", default=BRUSH_FONT_PATH, help="TTF/OTF/TTC 폰트 경로")
    parser.add_argument("--width-mm", type=float, default=60.0, help="글자 전체 폭 (mm)")
    parser.add_argument("--pen-z-offset", type=float, default=PEN1_BASE_Z_OFFSET, help="기준 막대 대비 1번 펜 기본 높이 오프셋(mm)")
    parser.add_argument("--gap-mm", type=float, default=20.0, help="첫 번째와 두 번째 글씨 사이 Y 간격(mm)")
    args, _ = parser.parse_known_args()

    font_path = args.font
    if not os.path.exists(font_path):
        node.get_logger().warning(
            f"붓글씨 폰트({font_path})를 찾을 수 없어 기본 폰트({DEFAULT_FONT})를 사용합니다. "
            "설치: sudo apt install -y fonts-nanum-extra"
        )
        font_path = DEFAULT_FONT

    with RunLogSession("draw_calligraphy"):
        try:
            # 0. 실행 즉시 미리보기 이미지 생성 및 창 띄우기
            os.makedirs("run_logs", exist_ok=True)
            safe_text = re.sub(r"[^\w가-힣-]+", "_", args.text).strip("_") or "text"
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            auto_preview_path = os.path.abspath(
                os.path.join("run_logs", f"preview_{safe_text}_{ts}.png")
            )
            generate_calligraphy_paths(
                text=args.text,
                font_path=font_path,
                target_width_mm=args.width_mm,
                preview_path=auto_preview_path,
            )
            node.get_logger().info(f"[미리보기 저장] {auto_preview_path}")
            try:
                subprocess.Popen(
                    ["xdg-open", auto_preview_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                node.get_logger().warning(f"미리보기 자동 열기 실패: {exc}")

            set_tool(TOOL_NAME)
            set_tcp(TCP_NAME)

            stick_pose = load_stick_slot()
            first_pen_pose = load_first_pen_slot()

            # 1. 홈 위치 [0, 0, 90, 0, 90, 0]에서 시작
            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)

            # 2. 기준 막대 집기 -> 종이 바닥 높이 측정 -> 기준 막대 원위치
            pick_from_slot(stick_pose, "기준 막대")
            contact_pose = measure_floor_height_with_stick()
            return_to_slot(stick_pose, "기준 막대")

            # 3. 1번 펜 집기
            pick_from_slot(first_pen_pose, "펜 1")

            # 4. 굵기 없는 버전 먼저 그리기
            flat_strokes = draw_calligraphy_text(
                args.text,
                font_path,
                args.width_mm,
                contact_pose,
                pen_z_offset=args.pen_z_offset,
                use_thickness=False,
                offset_x_mm=0.0,
                offset_y_mm=0.0,
            )

            # 5. 안 겹치도록 Y축 아래로 간격(--gap-mm)을 띄워 굵기 있는 버전 그리기
            all_y = [pt[1] for stroke in flat_strokes for pt in stroke]
            second_offset_y = min(all_y) - max(all_y) - args.gap_mm
            draw_calligraphy_text(
                args.text,
                font_path,
                args.width_mm,
                contact_pose,
                pen_z_offset=args.pen_z_offset,
                use_thickness=True,
                offset_x_mm=0.0,
                offset_y_mm=second_offset_y,
            )

            # 6. 안전 상승 -> 1번 펜 반납 -> 홈 위치 복귀
            movel([0.0, 0.0, END_LIFT_MM, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
            return_to_slot(first_pen_pose, "펜 1")
            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
            set_gripper_state(OFF, OFF, "기본")

            node.get_logger().info("기준 막대 측정 -> 1번 펜 굵기 없는/있는 버전 그리기 -> 펜 반납 및 홈 복귀 완료!")
        except Exception as exc:
            node.get_logger().error(f"draw_calligraphy 중단: {exc}")
            raise
        finally:
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
