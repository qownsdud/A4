"""PC 키보드 기반 로봇팔 수동 조종(조그 / 그리퍼 / 상태 조회 / 홈 이동) 전용 노드."""

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

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init(args=None)
node = rclpy.create_node("manual_move", namespace=ROBOT_ID)
DR_init.__dsr__node = node

try:
    from DSR_ROBOT2 import (
        set_tool,
        set_tcp,
        movej,
        movel,
        get_current_posj,
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


def read_force() -> List[float]:
    """Base 기준 외력 [Fx, Fy, Fz, ...] (N)를 반환한다."""
    return [float(v) for v in get_tool_force(DR_BASE)[:6]]


def print_status(baseline_fz: float) -> None:
    """현재 TCP 좌표, 관절 각도, 외력을 출력한다."""
    pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
    joints = [float(v) for v in get_current_posj()[:6]]
    force = read_force()
    print(
        f"  -> PosX : [{pose[0]:.2f}, {pose[1]:.2f}, {pose[2]:.2f}, "
        f"{pose[3]:.2f}, {pose[4]:.2f}, {pose[5]:.2f}]\n"
        f"  -> PosJ : [{', '.join(f'{j:.2f}' for j in joints)}]\n"
        f"  -> Force: Fx={force[0]:.3f}, Fy={force[1]:.3f}, Fz={force[2]:.3f} N "
        f"(deltaFz={force[2] - baseline_fz:+.3f} N)"
    )


def set_gripper_state(pin1: int, pin2: int, label: str) -> None:
    """디지털 출력 1, 2번 핀으로 그리퍼 상태를 설정한다."""
    set_digital_output(1, OFF)
    set_digital_output(2, OFF)
    if pin1 != OFF or pin2 != OFF:
        set_digital_output(1, pin1)
        set_digital_output(2, pin2)
    time.sleep(0.3)
    print(f"  -> 그리퍼: {label} (DO1={pin1}, DO2={pin2})")


def print_help(step_mm: float, jog_vel: float) -> None:
    print(
        f"\n[로봇 조종 안내] step={step_mm:g} mm | vel={jog_vel:g} mm/s\n"
        "  조그 이동 : w(+X), s(-X), a(+Y), d(-Y), e(+Z), c(-Z)\n"
        "              (예: 'w' -> 현재 step 이동 / 'w 10' -> +X 10mm 이동)\n"
        "  이동량변경: 숫자만 입력 (예: '10', '1', '0.2')\n"
        "  속도 변경 : vel <값> (예: 'vel 50')\n"
        "  그리퍼    : g (잡기: 1 ON, 2 OFF) | f (놓기: 1 OFF, 2 ON) | n (기본: 1 OFF, 2 OFF)\n"
        "  조회/이동 : p (좌표/외력 전체) | fz (외력만) | home (홈 이동) | help | q (종료)\n"
    )


def main() -> None:
    set_tool(TOOL_NAME)
    set_tcp(TCP_NAME)

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

    baseline_fz = read_force()[2]
    print_help(step_mm, jog_vel)
    print_status(baseline_fz)

    try:
        while True:
            raw = input(f"\n[step={step_mm:g}mm | vel={jog_vel:g}] > ").strip()
            if not raw:
                continue

            parts = raw.lower().split()
            cmd = parts[0]

            if cmd == "q":
                break
            if cmd == "help":
                print_help(step_mm, jog_vel)
                continue
            if cmd == "p":
                print_status(baseline_fz)
                continue
            if cmd == "fz":
                f = read_force()
                print(
                    f"  -> Force: Fx={f[0]:.3f}, Fy={f[1]:.3f}, Fz={f[2]:.3f} N "
                    f"(deltaFz={f[2] - baseline_fz:+.3f} N)"
                )
                continue
            if cmd == "home":
                movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
                time.sleep(0.1)
                print_status(baseline_fz)
                continue
            if cmd == "vel":
                if len(parts) < 2:
                    print("  -> 사용법: vel <속도> (예: vel 50)")
                    continue
                try:
                    new_vel = float(parts[1])
                    if new_vel <= 0.0:
                        print("  -> 속도는 0보다 커야 합니다.")
                    else:
                        jog_vel = new_vel
                        print(f"  -> 이동 속도 변경: {jog_vel:g} mm/s")
                except ValueError:
                    print("  -> 속도는 숫자로 입력하세요.")
                continue

            # 그리퍼 제어
            if cmd == "g":
                set_gripper_state(ON, OFF, "잡기")
                continue
            if cmd == "f":
                set_gripper_state(OFF, ON, "놓기")
                continue
            if cmd == "n":
                set_gripper_state(OFF, OFF, "기본")
                continue

            # 조그 이동
            if cmd in axis_map:
                dist = step_mm
                if len(parts) >= 2:
                    try:
                        dist = float(parts[1])
                    except ValueError:
                        print("  -> 이동 거리는 숫자로 입력하세요 (예: w 10)")
                        continue
                ux, uy, uz = axis_map[cmd]
                movel(
                    [ux * dist, uy * dist, uz * dist, 0.0, 0.0, 0.0],
                    vel=jog_vel,
                    acc=jog_vel,
                    mod=DR_MV_MOD_REL,
                )
                time.sleep(0.1)
                pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
                fz = read_force()[2]
                print(
                    f"  -> Pos: X={pose[0]:.2f}, Y={pose[1]:.2f}, Z={pose[2]:.2f} | "
                    f"Fz={fz:.3f} N (delta={fz - baseline_fz:+.3f} N)"
                )
                continue

            # 숫자만 입력 시 step_mm 변경
            try:
                new_step = float(cmd)
                if new_step <= 0.0:
                    print("  -> 이동량은 0보다 커야 합니다.")
                else:
                    step_mm = new_step
                    print(f"  -> 이동량 변경: {step_mm:g} mm")
            except ValueError:
                print("  -> 알 수 없는 명령입니다. ('help' 입력 시 안내 출력)")
    except KeyboardInterrupt:
        print("\n조종 종료")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
