"""draw_image_standalone의 9점 빈 그리퍼 재캘리브레이션 및 기준 막대 포스 접촉 측정을 수행합니다."""

import math
import time
import numpy as np

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
CONTACT_SIGN = 1

CALIBRATE_INSET_MM = 40.0
GRIPPER_PROBE_START_OFFSET_Z = 15.0
GRIPPER_PROBE_MAX_TRAVEL_MM = 30.0
DEFAULT_HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
DEFAULT_READY_OFFSET = [0.0, 0.0, -100.0, 0.0, 0.0, 0.0]


def _read_fz_avg(adapter, samples=READ_SAMPLES):
    vals = []
    for i in range(samples):
        val = float(adapter.read_tool_force_z(0))
        if not math.isfinite(val):
            raise RuntimeError("Fz 센서 측정값이 유효하지 않습니다.")
        vals.append(val)
        if i < samples - 1:
            time.sleep(SAMPLE_INTERVAL_S)
    return sum(vals) / len(vals)


def probe_floor_contact(adapter, runner, max_travel_mm, label):
    """현재 위치에서 -Z로 하강하며 포스 접촉 바닥 pose를 반환합니다."""
    settings = adapter.settings
    probe_vel = settings.get("probe_velocity", 5.0)
    probe_acc = settings.get("probe_acceleration", 5.0)

    base_samples = [_read_fz_avg(adapter, 1) for _ in range(BASELINE_SAMPLES)]
    baseline_fz = sum(base_samples) / len(base_samples)
    if (max(base_samples) - min(base_samples)) >= CONTACT_FORCE_DELTA_N:
        raise RuntimeError(f"[{label}] 센서 노이즈가 접촉 판정 기준 이상입니다.")

    descended = 0.0
    step_idx = 0
    hits = 0
    probe_baseline = None
    fine_mode = False

    while descended + 1e-9 < max_travel_mm:
        runner.check_cancel()
        cur_step = PROBE_FINE_STEP_MM if fine_mode else PROBE_STEP_MM
        step = min(cur_step, max_travel_mm - descended)
        runner.move([[0.0, 0.0, -step, 0.0, 0.0, 0.0]], probe_vel, probe_acc, mod=1)
        descended += step
        step_idx += 1
        time.sleep(SETTLE_TIME_S)
        cur_fz = _read_fz_avg(adapter)

        if CONTACT_SIGN * (cur_fz - baseline_fz) >= HARD_LIMIT_FORCE_N:
            raise RuntimeError(f"[{label}] 탐색 중 과압 감지로 중단합니다.")
        if step_idx <= WARMUP_STEPS:
            if step_idx == WARMUP_STEPS:
                probe_baseline = cur_fz
            continue

        delta = CONTACT_SIGN * (cur_fz - probe_baseline)
        if delta >= HARD_LIMIT_FORCE_N:
            raise RuntimeError(
                f"[{label}] 탐색 중 과압 감지로 중단합니다. (dFz={delta:.2f} N)"
            )
        if delta >= CONTACT_FORCE_DELTA_N:
            # 첫 접촉 감지 이후에는 정밀 탐색(0.1 mm) 모드로 전환해 과압 스파이크를 방지합니다.
            fine_mode = True
            hits += 1
            if hits >= CONFIRM_COUNT:
                return [float(v) for v in adapter.current_pose()[:6]]
        else:
            hits = 0
    raise RuntimeError(f"[{label}] 최대 하강 거리({max_travel_mm:.1f} mm) 내 접촉 미감지")


def calibrate_9pt_with_closed_gripper(adapter, runner, pens, points):
    """닫힌 빈 그리퍼로 9개 XY 지점의 Z를 재측정해 평면 기울기(a, b)를 갱신합니다."""
    settings = adapter.settings
    l_vel = settings.get("travel_velocity", 80.0)
    l_acc = settings.get("travel_acceleration", settings.get("acceleration", 80.0))
    p_vel = settings.get("pick_velocity", 25.0)
    p_acc = settings.get("pick_acceleration", settings.get("acceleration", 25.0))
    inset = settings.get("calibrate_inset_mm", CALIBRATE_INSET_MM)

    pens.gripper.grip(runner)

    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    cx = 0.5 * (min(xs) + max(xs))
    cy = 0.5 * (min(ys) + max(ys))

    measured_xyz = []
    last_z = None

    for idx, pt in enumerate(points, start=1):
        runner.check_cancel()
        x, y, z, rx, ry, rz = [float(v) for v in pt[:6]]
        if x < cx - 10.0:
            x += inset
        elif x > cx + 10.0:
            x -= inset
        if y < cy - 10.0:
            y += inset
        elif y > cy + 10.0:
            y -= inset

        start_z = (last_z + 10.0) if last_z is not None else (z + GRIPPER_PROBE_START_OFFSET_Z)
        transit_z = start_z + 30.0
        travel = 20.0 if last_z is not None else GRIPPER_PROBE_MAX_TRAVEL_MM

        runner.move([[x, y, transit_z, rx, ry, rz]], l_vel, l_acc)
        runner.move([[x, y, start_z, rx, ry, rz]], p_vel, p_acc)
        contact = probe_floor_contact(adapter, runner, travel, f"9점-{idx}/9")
        last_z = contact[2]
        measured_xyz.append((x, y, last_z))
        runner.move([[x, y, transit_z, rx, ry, rz]], l_vel, l_acc)

    arr = np.array(measured_xyz, dtype=np.float64)
    mat = np.column_stack([arr[:, 0], arr[:, 1], np.ones(len(arr))])
    a_new, b_new, _ = np.linalg.lstsq(mat, arr[:, 2], rcond=None)[0]
    return float(a_new), float(b_new)


def measure_floor_height_with_stick(adapter, runner):
    """홈에서 READY_OFFSET만큼 하강한 뒤 기준 막대로 바닥 접촉 Z를 측정합니다."""
    settings = adapter.settings
    j_vel = settings.get("joint_velocity", 60.0)
    j_acc = settings.get("joint_acceleration", 60.0)
    l_vel = settings.get("travel_velocity", 80.0)
    l_acc = settings.get("travel_acceleration", settings.get("acceleration", 80.0))
    home_joints = settings.get("home_joints", DEFAULT_HOME_JOINTS)
    ready_offset = settings.get("ready_offset", DEFAULT_READY_OFFSET)
    approach_z = settings.get("slot_approach_mm", 100.0)

    runner.check_cancel()
    runner.move_joint(home_joints, j_vel, j_acc)
    runner.check_cancel()
    runner.move([list(ready_offset)], l_vel, l_acc, mod=1)
    contact_pose = probe_floor_contact(adapter, runner, PROBE_MAX_TRAVEL_MM, "기준 막대")
    runner.move([[0.0, 0.0, approach_z, 0.0, 0.0, 0.0]], l_vel, l_acc, mod=1)
    return contact_pose


def run_pre_drawing_calibration(adapter, runner, pens):
    """draw_image_standalone과 동일하게 툴 설정·홈 이동·9점 재캘리브레이션·기준 막대 측정을 실행합니다."""
    if not (
        hasattr(adapter, "read_tool_force_z")
        and hasattr(adapter, "move_joint")
        and getattr(adapter, "control", None) is not None
    ):
        return False

    settings = adapter.settings
    cal_points = settings.get("calibration_points")
    stick_pose = settings.get("stick_pose")
    if not cal_points and not stick_pose:
        return False

    j_vel = settings.get("joint_velocity", 60.0)
    j_acc = settings.get("joint_acceleration", 60.0)
    home_joints = settings.get("home_joints", DEFAULT_HOME_JOINTS)

    if hasattr(adapter, "set_tool_and_tcp"):
        adapter.set_tool_and_tcp()

    pens.gripper.release(runner)
    pens.gripper.grip(runner)
    runner.check_cancel()
    runner.move_joint(home_joints, j_vel, j_acc)
    runner.check_cancel()

    slope_a, slope_b = float(settings["plane_abc"][0]), float(settings["plane_abc"][1])
    if settings.get("auto_calibrate_9pt", True) and cal_points:
        slope_a, slope_b = calibrate_9pt_with_closed_gripper(adapter, runner, pens, cal_points)
        runner.move_joint(home_joints, j_vel, j_acc)
        runner.check_cancel()

    if stick_pose:
        rz_offset = settings.get("stick_grip_rz_offset_deg", -45.0)
        stick_grip_pose = [
            float(stick_pose[0]),
            float(stick_pose[1]),
            float(stick_pose[2]),
            float(stick_pose[3]),
            float(stick_pose[4]),
            float(stick_pose[5]) + float(rz_offset),
        ]
        pens.pick_from_slot(stick_grip_pose)
        adapter.held_stick_pose = stick_grip_pose
        contact_pose = measure_floor_height_with_stick(adapter, runner)
        pens.return_to_slot(
            stick_grip_pose,
            on_released=lambda: setattr(adapter, "held_stick_pose", None),
        )
        bx, by, contact_z = contact_pose[0], contact_pose[1], contact_pose[2]
        settings["plane_abc"] = [
            slope_a,
            slope_b,
            contact_z - slope_a * bx - slope_b * by,
        ]
    else:
        ox, oy, oz = settings["paper_origin_base_mm"]
        settings["plane_abc"] = [slope_a, slope_b, oz - slope_a * ox - slope_b * oy]
    return True
