"""9점 키보드 조그 티칭 기반 바닥 기울기 보정 및 평탄도 확인 스크립트.

기능:
- PC 키보드로 X/Y/Z 조그 이동 (원하는 이동량 실시간 변경 가능)
- 그리퍼 조작: 기본(1 OFF, 2 OFF), 잡기(1 ON, 2 OFF), 놓기(1 OFF, 2 ON)
- 각 위치에서 'O' 입력 시 현재 TCP 좌표 기록 (9점 반복)
- 9점 수집 완료 후 최소자승법 평면 피팅(z = a*x + b*y + c), 기울기, 평탄도 계산 및 JSON 저장
"""

import json
import math
import os
import time
from typing import Any, Dict, List, Optional

import numpy as np
import rclpy
import DR_init

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"

JOG_VEL, JOG_ACC = 30, 30
DEFAULT_STEP_MM = 5.0
NUM_POINTS = 9
ON, OFF = 1, 0
CALIBRATION_FILE = os.path.expanduser("~/.ros/plane_calibration.json")

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init(args=None)
node = rclpy.create_node("plane_calibrator", namespace=ROBOT_ID)
DR_init.__dsr__node = node

try:
    from DSR_ROBOT2 import (
        set_tool,
        set_tcp,
        movel,
        get_current_posx,
        get_tool_force,
        set_digital_output,
        DR_MV_MOD_REL,
        DR_BASE,
    )
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


def read_force() -> List[float]:
    """Base 기준 외력 [Fx, Fy, Fz, ...] (N)를 반환한다."""
    return [float(v) for v in get_tool_force(DR_BASE)[:6]]


def jog_move(dx: float, dy: float, dz: float, baseline_fz: float) -> List[float]:
    """상대 좌표(dx, dy, dz)만큼 이동하고 현재 TCP 좌표와 외력 Fz를 출력·반환한다."""
    movel([dx, dy, dz, 0.0, 0.0, 0.0], vel=JOG_VEL, acc=JOG_ACC, mod=DR_MV_MOD_REL)
    time.sleep(0.1)
    pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
    fz = read_force()[2]
    print(
        f"  -> 현재 위치: X={pose[0]:.2f}, Y={pose[1]:.2f}, Z={pose[2]:.2f} | "
        f"Fz={fz:.3f} N (delta={fz - baseline_fz:+.3f} N)"
    )
    return pose


def fit_plane(points: List[List[float]]) -> Dict[str, Any]:
    """9개 이상의 [x, y, z, ...] 점으로부터 평면 z = a*x + b*y + c 및 평탄도를 계산한다."""
    arr = np.asarray(points, dtype=float)
    xs, ys, zs = arr[:, 0], arr[:, 1], arr[:, 2]

    design = np.column_stack([xs, ys, np.ones_like(xs)])
    coeffs, _, _, _ = np.linalg.lstsq(design, zs, rcond=None)
    a, b, c = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])

    z_pred = a * xs + b * ys + c
    residuals = zs - z_pred

    flatness_pv = float(np.max(residuals) - np.min(residuals))
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    slope_x_deg = math.degrees(math.atan(a))
    slope_y_deg = math.degrees(math.atan(b))
    tilt_deg = math.degrees(math.atan(math.hypot(a, b)))

    return {
        "a": a,
        "b": b,
        "c": c,
        "slope_x_deg": slope_x_deg,
        "slope_y_deg": slope_y_deg,
        "tilt_deg": tilt_deg,
        "flatness_pv_mm": flatness_pv,
        "rmse_mm": rmse,
        "residuals_mm": [float(r) for r in residuals],
        "points": [[float(v) for v in p] for p in points],
    }


def eval_plane_z(cal: Dict[str, Any], x: float, y: float) -> float:
    """저장된 캘리브레이션 결과로 임의의 (x, y) 위치의 보정된 바닥 Z를 계산한다."""
    return float(cal["a"]) * x + float(cal["b"]) * y + float(cal["c"])


def load_plane_calibration(path: str = CALIBRATION_FILE) -> Optional[Dict[str, Any]]:
    """저장된 평면 캘리브레이션 JSON을 불러온다. 없으면 None 반환."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_plane_calibration(result: Dict[str, Any], path: str = CALIBRATION_FILE) -> None:
    """평면 캘리브레이션 결과를 JSON 파일로 저장한다."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


def print_report(result: Dict[str, Any]) -> None:
    """기울기 및 평탄도 분석 결과를 터미널에 출력한다."""
    print("\n" + "=" * 60)
    print("[9점 바닥 평면 캘리브레이션 결과]")
    print(f"평면 방정식 : z = ({result['a']:+.6f}) * x + ({result['b']:+.6f}) * y + ({result['c']:+.3f})")
    print(f"X축 기울기  : {result['slope_x_deg']:+.3f} deg ({result['a'] * 100:+.3f} mm / 100mm)")
    print(f"Y축 기울기  : {result['slope_y_deg']:+.3f} deg ({result['b'] * 100:+.3f} mm / 100mm)")
    print(f"총 기울기   : {result['tilt_deg']:.3f} deg")
    print(f"평탄도(P-V) : {result['flatness_pv_mm']:.3f} mm  (최고-최저 편차)")
    print(f"평면 RMSE   : {result['rmse_mm']:.3f} mm")
    print("-" * 60)
    print("번호 |     X (mm) |     Y (mm) |     Z (mm) |  평면 오차(mm)")
    for idx, (pt, err) in enumerate(zip(result["points"], result["residuals_mm"]), start=1):
        print(f"  {idx:2d} | {pt[0]:10.3f} | {pt[1]:10.3f} | {pt[2]:10.3f} | {err:+12.3f}")
    print("=" * 60)


def print_help(step_mm: float) -> None:
    print(
        f"\n[조작 안내] 현재 이동량 = {step_mm:.2f} mm\n"
        "  조그 이동 : w(+X), s(-X), a(+Y), d(-Y), e(+Z), c(-Z)\n"
        "              (예: 'w' -> 현재 이동량만큼 / 'w 10' -> +X 10mm 즉시 이동)\n"
        "  이동량변경: 숫자만 입력 (예: '10', '1', '0.2')\n"
        "  그리퍼    : g (잡기: 1 ON, 2 OFF) | f (놓기: 1 OFF, 2 ON) | n (기본: 1 OFF, 2 OFF)\n"
        "  외력/기록 : fz (현재 외력 조회) | o (현재 위치 기록) | undo (직전 취소) | q (중단)\n"
    )


def collect_points_with_jog(count: int = NUM_POINTS) -> List[List[float]]:
    """키보드 조그 및 그리퍼 조작 후 'O' 입력 시 좌표를 9번 기록한다."""
    points: List[List[float]] = []
    step_mm = DEFAULT_STEP_MM
    axis_map = {
        "w": (1.0, 0.0, 0.0),
        "s": (-1.0, 0.0, 0.0),
        "a": (0.0, 1.0, 0.0),
        "d": (0.0, -1.0, 0.0),
        "e": (0.0, 0.0, 1.0),
        "c": (0.0, 0.0, -1.0),
    }

    print_help(step_mm)
    cur = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
    baseline_fz = read_force()[2]
    print(f"시작 위치: X={cur[0]:.2f}, Y={cur[1]:.2f}, Z={cur[2]:.2f} | 기준 Fz={baseline_fz:.3f} N")

    while len(points) < count:
        idx = len(points) + 1
        raw = input(f"\n[{idx}/{count} | step={step_mm:g}mm] 명령 입력 > ").strip()
        if not raw:
            continue

        parts = raw.lower().split()
        cmd = parts[0]

        if cmd == "q":
            raise KeyboardInterrupt("사용자 요청으로 캘리브레이션을 중단했습니다.")
        if cmd == "help":
            print_help(step_mm)
            continue
        if cmd == "undo":
            if points:
                removed = points.pop()
                print(f"  -> {len(points) + 1}번 점({removed[0]:.2f}, {removed[1]:.2f}, {removed[2]:.2f}) 취소됨")
            else:
                print("  -> 취소할 이전 점이 없습니다.")
            continue

        # 그리퍼 제어 (1off 2off: 기본, 1on 2off: 잡기, 1off 2on: 놓기)
        if cmd == "g":
            set_gripper_state(ON, OFF, "잡기")
            continue
        if cmd == "f":
            set_gripper_state(OFF, ON, "놓기")
            continue
        if cmd == "n":
            set_gripper_state(OFF, OFF, "기본")
            continue

        # 외력 조회 ('fz')
        if cmd == "fz":
            f = read_force()
            print(
                f"  -> 외력: Fx={f[0]:.3f}, Fy={f[1]:.3f}, Fz={f[2]:.3f} N "
                f"(deltaFz={f[2] - baseline_fz:+.3f} N)"
            )
            continue

        # 좌표 기록 ('O' 또는 'o')
        if cmd == "o":
            pose = [float(v) for v in get_current_posx(DR_BASE)[0][:6]]
            fz = read_force()[2]
            points.append(pose)
            print(
                f"  -> {idx}번 점 기록: X={pose[0]:.3f}, Y={pose[1]:.3f}, Z={pose[2]:.3f} | "
                f"Fz={fz:.3f} N (delta={fz - baseline_fz:+.3f} N)"
            )
            continue

        # 조그 이동 (예: 'w' 또는 'w 10')
        if cmd in axis_map:
            dist = step_mm
            if len(parts) >= 2:
                try:
                    dist = float(parts[1])
                except ValueError:
                    print("  -> 이동 거리는 숫자로 입력하세요 (예: w 10)")
                    continue
            ux, uy, uz = axis_map[cmd]
            jog_move(ux * dist, uy * dist, uz * dist, baseline_fz)
            continue

        # 숫자만 입력 시 step_mm 변경
        try:
            new_step = float(cmd)
            if new_step <= 0.0:
                print("  -> 이동량은 0보다 커야 합니다.")
            else:
                step_mm = new_step
                print(f"  -> 이동량 변경: {step_mm:g} mm")
            continue
        except ValueError:
            print("  -> 알 수 없는 명령입니다. ('help' 입력 시 안내 출력)")

    return points


def main() -> None:
    set_tool(TOOL_NAME)
    set_tcp(TCP_NAME)
    set_gripper_state(OFF, OFF, "기본")

    try:
        points = collect_points_with_jog(NUM_POINTS)
        result = fit_plane(points)
        save_plane_calibration(result, CALIBRATION_FILE)
        print_report(result)
        print(f"저장 완료: {CALIBRATION_FILE}\n")
    except KeyboardInterrupt as exc:
        print(f"\n{exc}")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
