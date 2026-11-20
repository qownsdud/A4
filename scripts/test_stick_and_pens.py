#!/usr/bin/env python3
"""기준 막대 바닥 높이 측정 및 펜 1~4 슬롯 픽업·테스트 드로잉·반납을 개별 점검하는 스크립트.

사용 예시:
  # 1) 로봇 이동 없이 설정/좌표만 확인
  python3 scripts/test_stick_and_pens.py --dry-run

  # 2) 기준 막대 높이 측정 + 펜 1~4 전체 테스트 (각 펜으로 짧은 직선 1개씩 그리기)
  python3 scripts/test_stick_and_pens.py

  # 3) 기준 막대 측정만 테스트
  python3 scripts/test_stick_and_pens.py --only-stick

  # 4) 4번 펜만 단독 테스트 (기준 막대 측정 후 4번 펜 집기 -> 선 1개 -> 반납)
  python3 scripts/test_stick_and_pens.py --pens 4

  # 5) 그리기 없이 집기/반납 동작만 테스트
  python3 scripts/test_stick_and_pens.py --pens 4 --no-draw
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import select
import sys
import termios
import threading
import time
import tty
from typing import List, Optional, Tuple

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"

J_VEL, J_ACC = 50, 50
L_VEL, L_ACC = 80, 80
PICK_VEL, PICK_ACC = 25, 25
PROBE_VEL, PROBE_ACC = 5, 5
DRAW_VEL, DRAW_ACC = 25, 25

HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
READY_OFFSET = [0.0, 0.0, -100.0, 0.0, 0.0, 0.0]
APPROACH_OFFSET_Z = 100.0
STROKE_LIFT_MM = 15.0
STICK_GRIP_RZ_OFFSET_DEG = -45.0

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

PEN_Z_OFFSETS = [11.8, 12.3, 12.8, 12.5]
ON, OFF = 1, 0

A4_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = A4_ROOT / "config"


class TestAborted(RuntimeError):
    """사용자 중단('x') 시 안전 복귀를 위해 발생합니다."""


def _load_json(path: Path, label: str):
    if not path.is_file():
        raise FileNotFoundError(f"{label} 파일이 없습니다: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def run_hardware_test(
    *,
    stick_pose: List[float],
    pen_poses: List[List[float]],
    slope_a: float,
    slope_b: float,
    cal_points: List[List[float]],
    selected_pens: List[int],
    only_stick: bool,
    no_draw: bool,
    z_offset: float,
    virtual: bool,
) -> None:
    import rclpy
    import DR_init

    DR_init.__dsr__id = ROBOT_ID
    DR_init.__dsr__model = ROBOT_MODEL

    rclpy.init(args=None)
    node = rclpy.create_node("test_stick_and_pens", namespace=ROBOT_ID)
    DR_init.__dsr__node = node

    import DSR_ROBOT2 as _dsr
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

    abort_event = threading.Event()
    stop_listener = threading.Event()
    held_item: Optional[Tuple[List[float], str]] = None

    def check_abort() -> None:
        if abort_event.is_set():
            raise TestAborted("사용자 중단('x') 요청으로 안전 복귀를 시작합니다.")

    def _keyboard_listener() -> None:
        if not sys.stdin or not sys.stdin.isatty():
            return
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not stop_listener.is_set() and not abort_event.is_set():
                rlist, _, _ = select.select([fd], [], [], 0.1)
                if rlist and sys.stdin.read(1).lower() == "x":
                    abort_event.set()
                    node.get_logger().warn("중단 키('x') 감지 -> 현재 동작 후 안전 복귀합니다.")
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
        node.get_logger().info(f"[{name}] 집기 시작 (target={target})")
        set_gripper(OFF, ON, "열기")
        movel(approach, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
        movel(target, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
        set_gripper(ON, OFF, "잡기")
        held_item = (list(slot_pose), name)
        movel(approach, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
        node.get_logger().info(f"[{name}] 집기 완료")

    def return_to_slot(slot_pose: List[float], name: str) -> None:
        nonlocal held_item
        x, y, z, rx, ry, rz = slot_pose
        approach = posx([x, y, z + APPROACH_OFFSET_Z, rx, ry, rz])
        target = posx([x, y, z, rx, ry, rz])
        node.get_logger().info(f"[{name}] 원위치 반납 시작")
        movel(approach, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
        movel(target, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
        set_gripper(OFF, ON, "놓기")
        held_item = None
        movel(approach, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
        node.get_logger().info(f"[{name}] 반납 완료")

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

    def probe_floor_contact() -> List[float]:
        base_samples = [read_fz_avg(1) for _ in range(BASELINE_SAMPLES)]
        baseline_fz = sum(base_samples) / len(base_samples)
        if (max(base_samples) - min(base_samples)) >= CONTACT_FORCE_DELTA_N:
            raise RuntimeError("Fz 센서 노이즈가 접촉 판정 기준 이상입니다.")

        descended, step_idx, hits, probe_baseline = 0.0, 0, 0, None
        fine_mode = False
        while descended + 1e-9 < PROBE_MAX_TRAVEL_MM:
            check_abort()
            cur_step = PROBE_FINE_STEP_MM if fine_mode else PROBE_STEP_MM
            step = min(cur_step, PROBE_MAX_TRAVEL_MM - descended)
            movel([0.0, 0.0, -step, 0.0, 0.0, 0.0], vel=PROBE_VEL, acc=PROBE_ACC, mod=DR_MV_MOD_REL)
            descended += step
            step_idx += 1
            time.sleep(SETTLE_TIME_S)
            cur_fz = read_fz_avg()
            if CONTACT_SIGN * (cur_fz - baseline_fz) >= HARD_LIMIT_FORCE_N:
                raise RuntimeError("과압 감지로 중단합니다.")
            if step_idx <= WARMUP_STEPS:
                if step_idx == WARMUP_STEPS:
                    probe_baseline = cur_fz
                continue
            delta = CONTACT_SIGN * (cur_fz - probe_baseline)
            if not fine_mode and delta >= CONTACT_FORCE_DELTA_N * 0.5:
                fine_mode = True
            if delta >= CONTACT_FORCE_DELTA_N:
                hits += 1
                if hits >= CONFIRM_COUNT:
                    pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
                    node.get_logger().info(f"[기준 막대] 바닥 접촉 확인 Z={pose[2]:.2f} mm (delta={delta:+.2f} N)")
                    return pose
            else:
                hits = 0
        raise RuntimeError(f"최대 하강 거리({PROBE_MAX_TRAVEL_MM:.1f} mm) 내 바닥 접촉 미감지")

    stick_grip_pose = [
        stick_pose[0],
        stick_pose[1],
        stick_pose[2],
        stick_pose[3],
        stick_pose[4],
        stick_pose[5] + STICK_GRIP_RZ_OFFSET_DEG,
    ]

    listener = threading.Thread(target=_keyboard_listener, daemon=True)
    listener.start()
    node.get_logger().info("테스트 중 'x'를 누르면 안전하게 반납 후 홈으로 복귀합니다.")

    try:
        if hasattr(_dsr, "_ros2_move_joint"):
            if not _dsr._ros2_move_joint.wait_for_service(timeout_sec=15.0):
                raise RuntimeError("로봇 모션 서비스(/dsr01/dsr_controller2)에 연결할 수 없습니다.")
        if not virtual:
            from DSR_ROBOT2 import set_robot_mode, ROBOT_MODE_MANUAL, ROBOT_MODE_AUTONOMOUS
            if hasattr(_dsr, "_ros2_set_current_tool") and not _dsr._ros2_set_current_tool.wait_for_service(timeout_sec=15.0):
                raise RuntimeError("로봇 툴 서비스에 연결할 수 없습니다.")
            set_robot_mode(ROBOT_MODE_MANUAL)
            try:
                set_tool(TOOL_NAME)
                set_tcp(TCP_NAME)
            finally:
                set_robot_mode(ROBOT_MODE_AUTONOMOUS)

        set_gripper(OFF, ON, "초기 정렬 - 열기")
        set_gripper(ON, OFF, "초기 정렬 - 닫기")
        movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)

        # 1. 기준 막대 바닥 높이 측정
        if virtual:
            pick_from_slot(stick_grip_pose, "기준 막대(가상)")
            contact_pose = [float(v) for v in cal_points[0][:6]]
            return_to_slot(stick_grip_pose, "기준 막대(가상)")
        else:
            pick_from_slot(stick_grip_pose, "기준 막대")
            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
            movel(posx(READY_OFFSET), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
            contact_pose = probe_floor_contact()
            movel([0.0, 0.0, APPROACH_OFFSET_Z, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
            return_to_slot(stick_grip_pose, "기준 막대")

        node.get_logger().info(f"측정된 기준 pose: x={contact_pose[0]:.2f}, y={contact_pose[1]:.2f}, z={contact_pose[2]:.2f}")

        if not only_stick:
            bx, by, contact_z, rx, ry, rz = contact_pose
            for pen_num in selected_pens:
                check_abort()
                idx = pen_num - 1
                pen_name = f"펜 {pen_num}"
                pick_from_slot(pen_poses[idx], pen_name)

                if not no_draw:
                    # 펜마다 Y 방향으로 15mm 간격으로 30mm 길이 테스트 직선 1개 그리기
                    tx = bx - 30.0
                    ty = by - 30.0 + idx * 15.0
                    pen_z = z_offset if z_offset is not None else PEN_Z_OFFSETS[idx]
                    tz1 = contact_z + slope_a * (tx - bx) + slope_b * (ty - by) + pen_z
                    tz2 = contact_z + slope_a * ((tx + 30.0) - bx) + slope_b * (ty - by) + pen_z
                    node.get_logger().info(f"[{pen_name}] 테스트 직선 그리기: X={tx:.1f}->{tx+30.0:.1f}, Y={ty:.1f}, Z={tz1:.2f}")
                    movel(posx([tx, ty, tz1 + STROKE_LIFT_MM, rx, ry, rz]), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
                    movel(posx([tx, ty, tz1, rx, ry, rz]), vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
                    movel(posx([tx + 30.0, ty, tz2, rx, ry, rz]), vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_ABS)
                    movel(posx([tx + 30.0, ty, tz2 + STROKE_LIFT_MM, rx, ry, rz]), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)

                return_to_slot(pen_poses[idx], pen_name)

        movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
        set_gripper(OFF, OFF, "기본")
        node.get_logger().info("기준 막대 + 펜 테스트 완료!")
    except TestAborted as exc:
        node.get_logger().warn(str(exc))
        cur_pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
        if held_item is not None:
            held_pose, held_name = held_item
            safe_z = max(cur_pose[2] + STROKE_LIFT_MM, held_pose[2] + APPROACH_OFFSET_Z)
            movel(posx([cur_pose[0], cur_pose[1], safe_z, cur_pose[3], cur_pose[4], cur_pose[5]]), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
            return_to_slot(held_pose, held_name)
        movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
        set_gripper(OFF, OFF, "기본")
    finally:
        stop_listener.set()
        listener.join(timeout=0.5)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="기준 막대 높이 측정 + 1~4번 펜 개별 테스트")
    parser.add_argument("--only-stick", action="store_true", help="기준 막대 높이 측정만 테스트")
    parser.add_argument("--pens", type=int, nargs="+", default=[1, 2, 3, 4], choices=[1, 2, 3, 4], help="테스트할 펜 번호 목록 (기본: 1 2 3 4)")
    parser.add_argument("--no-draw", action="store_true", help="선 그리기 없이 집기/반납 동작만 테스트")
    parser.add_argument("--z-offset", type=float, default=None, help="전체 펜 공통 Z 오프셋(mm, 미지정 시 PEN_Z_OFFSETS 사용)")
    parser.add_argument("--virtual", action="store_true", help="가상 모드(포스 탐색 생략)")
    parser.add_argument("--dry-run", action="store_true", help="로봇 이동 없이 설정 파일 및 테스트 대상만 출력")
    args = parser.parse_args(argv)

    stick_pose = [float(v) for v in _load_json(CONFIG_DIR / "stick_slot.json", "기준 막대 위치")[:6]]
    pen_data = _load_json(CONFIG_DIR / "pen_slots.json", "펜 위치")
    pen_poses = [[float(v) for v in p[:6]] for p in pen_data]
    cal = _load_json(CONFIG_DIR / "plane_calibration.json", "9점 캘리브레이션")
    cal_points = cal.get("points", [])
    slope_a, slope_b = float(cal.get("a", 0.0)), float(cal.get("b", 0.0))

    if not args.only_stick:
        for p in args.pens:
            if p > len(pen_poses):
                raise ValueError(f"{p}번 펜 좌표가 {CONFIG_DIR / 'pen_slots.json'}에 없습니다 (현재 {len(pen_poses)}개).")

    print(f"[테스트 준비] config={CONFIG_DIR}")
    print(f"  - 기준 막대: {stick_pose}")
    print(f"  - 펜 슬롯 ({len(pen_poses)}개): 테스트 대상={[] if args.only_stick else args.pens}")
    for p in ([] if args.only_stick else args.pens):
        print(f"    * 펜 {p}: {pen_poses[p - 1]}")
    print(f"  - 그리기 옵션: only_stick={args.only_stick}, no_draw={args.no_draw}, z_offset={args.z_offset if args.z_offset is not None else PEN_Z_OFFSETS}, virtual={args.virtual}")

    if args.dry_run:
        return

    run_hardware_test(
        stick_pose=stick_pose,
        pen_poses=pen_poses,
        slope_a=slope_a,
        slope_b=slope_b,
        cal_points=cal_points,
        selected_pens=args.pens,
        only_stick=args.only_stick,
        no_draw=args.no_draw,
        z_offset=args.z_offset,
        virtual=args.virtual,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
