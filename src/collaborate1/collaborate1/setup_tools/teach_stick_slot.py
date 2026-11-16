"""기준 막대 잡는 위치를 키보드 조그로 티칭해 저장(~/.ros/stick_slot.json)하는 노드."""

import json
import os
import time
from typing import List

import rclpy
import DR_init

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"

HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
J_VEL, J_ACC = 60, 60
DEFAULT_JOG_VEL = 30.0
DEFAULT_STEP_MM = 5.0
ON, OFF = 1, 0
STICK_FILE = os.path.expanduser("~/.ros/stick_slot.json")

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init(args=None)
node = rclpy.create_node("teach_stick_slot", namespace=ROBOT_ID)
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
        DR_MV_MOD_REL,
        DR_BASE,
    )
    from DR_common2 import posj
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
    time.sleep(0.3)
    print(f"  -> 그리퍼: {label} (DO1={pin1}, DO2={pin2})")


def save_stick_slot(pose: List[float], path: str = STICK_FILE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pose, f, indent=2, ensure_ascii=False)
    print(f"\n기준 막대 위치 저장 완료: {path}")


def print_help(step_mm: float, jog_vel: float) -> None:
    print(
        f"\n[기준 막대 위치 티칭 안내] step={step_mm:g} mm | vel={jog_vel:g} mm/s\n"
        "  조그 이동  : w(+X), s(-X), a(+Y), d(-Y), e(+Z), c(-Z) (예: 'w 10')\n"
        "  이동량/속도: 숫자만 입력(step 변경) | vel <값>(속도 변경)\n"
        "  그리퍼     : g (잡기: 1 ON, 2 OFF) | f (놓기: 1 OFF, 2 ON) | n (기본)\n"
        "  기록/기타  : o (기준 막대 위치 저장) | home | p | q (중단)\n"
    )


def teach_stick_slot() -> List[float]:
    """키보드 조그로 기준 막대 잡는 위치 1곳을 직접 지정해 반환한다."""
    step_mm = DEFAULT_STEP_MM
    jog_vel = DEFAULT_JOG_VEL
    axis_map = {
        "w": (1.0, 0.0, 0.0),
        "s": (-1.0, 0.0, 0.0),
        "a": (0.0, 1.0, 0.0),
        "d": (0.0, -1.0, 0.0),
        "e": (0.0, 0.0, 1.0),
        "c": (0.0, 0.0, -1.0),
    }

    print_help(step_mm, jog_vel)
    cur = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
    print(f"시작 위치: X={cur[0]:.2f}, Y={cur[1]:.2f}, Z={cur[2]:.2f}")

    while True:
        raw = input(f"\n[기준 막대 | step={step_mm:g}mm | vel={jog_vel:g}] > ").strip()
        if not raw:
            continue

        parts = raw.lower().split()
        cmd = parts[0]

        if cmd == "q":
            raise KeyboardInterrupt("사용자 요청으로 기준 막대 티칭을 중단했습니다.")
        if cmd == "help":
            print_help(step_mm, jog_vel)
            continue
        if cmd == "p":
            pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
            fz = float(get_tool_force(DR_BASE)[2])
            print(f"  -> PosX: {[round(v, 2) for v in pose]} | Fz={fz:.3f} N")
            continue
        if cmd == "home":
            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
            continue
        if cmd == "vel":
            if len(parts) >= 2:
                try:
                    new_vel = float(parts[1])
                    if new_vel > 0.0:
                        jog_vel = new_vel
                        print(f"  -> 이동 속도 변경: {jog_vel:g} mm/s")
                except ValueError:
                    print("  -> 숫자를 입력하세요.")
            continue
        if cmd == "g":
            set_gripper_state(ON, OFF, "잡기")
            continue
        if cmd == "f":
            set_gripper_state(OFF, ON, "놓기")
            continue
        if cmd == "n":
            set_gripper_state(OFF, OFF, "기본")
            continue
        if cmd == "o":
            pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
            print(
                f"  -> 기준 막대 위치 기록: X={pose[0]:.2f}, Y={pose[1]:.2f}, Z={pose[2]:.2f}, "
                f"Rx={pose[3]:.2f}, Ry={pose[4]:.2f}, Rz={pose[5]:.2f}"
            )
            return pose

        if cmd in axis_map:
            dist = step_mm
            if len(parts) >= 2:
                try:
                    dist = float(parts[1])
                except ValueError:
                    print("  -> 이동 거리는 숫자로 입력하세요.")
                    continue
            ux, uy, uz = axis_map[cmd]
            movel([ux * dist, uy * dist, uz * dist, 0.0, 0.0, 0.0],
                  vel=jog_vel, acc=jog_vel, mod=DR_MV_MOD_REL)
            time.sleep(0.1)
            pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
            fz = float(get_tool_force(DR_BASE)[2])
            print(f"  -> Pos: X={pose[0]:.2f}, Y={pose[1]:.2f}, Z={pose[2]:.2f} | Fz={fz:.3f} N")
            continue

        try:
            new_step = float(cmd)
            if new_step > 0.0:
                step_mm = new_step
                print(f"  -> 이동량 변경: {step_mm:g} mm")
        except ValueError:
            print("  -> 알 수 없는 명령입니다. ('help' 입력 시 안내)")


def main() -> None:
    set_tool(TOOL_NAME)
    set_tcp(TCP_NAME)

    try:
        pose = teach_stick_slot()
        save_stick_slot(pose)
    except KeyboardInterrupt as exc:
        print(f"\n{exc}")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
