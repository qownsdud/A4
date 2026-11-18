"""실물 프로필 검증과 기존 보정 백업의 후보 프로필 변환. 물리 명령은 없습니다."""

from pathlib import Path
import hashlib
import json
import math

PENS = ("PEN_1", "PEN_2", "PEN_3")


def finite_vector(value, n, label):
    if (
        not isinstance(value, (list, tuple))
        or len(value) != n
        or any(type(x) not in (int, float) or not math.isfinite(x) for x in value)
    ):
        raise ValueError(f"{label}: 유한한 {n}개 수가 필요합니다.")
    return tuple(float(x) for x in value)


def validate_equipment(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("장비 프로필 버전이 잘못되었습니다.")
    if data.get("robot_model") != "m0609" or not data.get("robot_id"):
        raise ValueError("M0609 프로필과 로봇 ID가 필요합니다.")
    if not data.get("tool_name") or not data.get("tcp_name"):
        raise ValueError("장비에서 검증한 Tool/TCP 이름이 필요합니다.")
    if data.get("paper_mm") not in (
        {"width": 297.0, "height": 210.0},
        {"width": 210.0, "height": 297.0},
    ):
        raise ValueError("A4 가로 또는 세로 규격이 필요합니다.")
    for name in (
        "paper_origin_base_mm",
        "paper_x_axis",
        "paper_y_axis",
        "plane_abc",
        "orientation_deg",
    ):
        finite_vector(data.get(name), 3, name)
    x, y = data["paper_x_axis"], data["paper_y_axis"]
    if (
        abs(sum(v * v for v in x) - 1) > 1e-6
        or abs(sum(v * v for v in y) - 1) > 1e-6
        or abs(sum(a * b for a, b in zip(x, y))) > 1e-6
        or abs(x[2]) + abs(y[2]) > 1e-8
    ):
        raise ValueError(
            "종이 XY 축은 기준면 XY의 직교 단위 축이어야 합니다. Z는 평면식으로 적용합니다."
        )
    limits = data.get("limits_base_mm")
    if not isinstance(limits, list) or len(limits) != 3:
        raise ValueError("실물 검증한 XYZ 작업 공간이 필요합니다.")
    for pair in limits:
        lo, hi = finite_vector(pair, 2, "XYZ 한계")
        if lo >= hi:
            raise ValueError("XYZ 한계 순서 오류")
    for key in (
        "travel_z_mm",
        "stroke_lift_mm",
        "slot_approach_mm",
        "travel_velocity",
        "draw_velocity",
        "pick_velocity",
        "acceleration",
        "motion_timeout_sec",
    ):
        value = data.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key}: 양수가 필요합니다.")
    if not limits[2][0] <= data["travel_z_mm"] <= limits[2][1]:
        raise ValueError("안전 이동 높이가 한계 밖입니다.")
    if any(
        data[k] > 250
        for k in ("travel_velocity", "draw_velocity", "pick_velocity", "acceleration")
    ):
        raise ValueError("검토 범위를 초과한 속도·가속도입니다.")
    if data["motion_timeout_sec"] > 600:
        raise ValueError("모션 시간 제한은 600초 이하여야 합니다.")
    if data.get("use_spline") and data.get("spline_validated") is not True:
        raise ValueError("스플라인 실제 경로 검증이 필요합니다.")
    if (
        type(data.get("spline_max_points", 80)) is not int
        or not 2 <= data.get("spline_max_points", 80) <= 80
    ):
        raise ValueError("스플라인은 2~80점 단위로 나눕니다.")
    if (
        type(data.get("corner_angle_deg", 35.0)) not in (int, float)
        or not 0 < data.get("corner_angle_deg", 35.0) < 180
    ):
        raise ValueError("모서리 분할 각도가 잘못되었습니다.")
    for pen in PENS:
        info = data.get("pen_slots", {}).get(pen, {})
        finite_vector(info.get("pose"), 6, pen + " 슬롯")
        z = info.get("z_offset_mm")
        if type(z) not in (float, int) or not math.isfinite(z) or abs(z) > 100:
            raise ValueError("각 펜에서 측정한 그리기 Z 오프셋이 필요합니다.")
    io = data.get("gripper", {})
    ports = [io.get(k) for k in ("grip_output", "release_output")]
    if any(type(i) is not int or not 1 <= i <= 16 for i in ports) or ports[0] == ports[1]:
        raise ValueError("RG2 출력 채널을 설정해야 합니다.")
    inputs = [io.get(k) for k in ("grip_input", "release_input")]
    if any(i is not None for i in inputs):
        if (
            any(type(i) is not int or not 1 <= i <= 16 for i in inputs)
            or inputs[0] == inputs[1]
        ):
            raise ValueError("RG2 입력 채널 설정이 잘못되었습니다.")
    return data


def load_equipment_settings(path):
    path = Path(path).expanduser().resolve(strict=True)
    raw = path.read_bytes()
    data = json.loads(raw)
    validate_equipment(data)
    data["_profile_path"] = str(path)
    data["_profile_sha256"] = hashlib.sha256(raw).hexdigest()
    return data


def profile_unchanged(settings):
    return settings is not None


def load_default_equipment_settings():
    """로컬 ~/.ros 보정 파일을 자동 로드하고, 없으면 기본 설정을 반환합니다."""
    ros_dir = Path.home() / ".ros"
    plane_path = ros_dir / "plane_calibration.json"
    pens_path = ros_dir / "pen_slots.json"
    stick_path = ros_dir / "stick_slot.json"
    if plane_path.is_file() and pens_path.is_file():
        return validate_equipment(
            import_reference(
                plane_path,
                pens_path,
                stick_path if stick_path.is_file() else None,
            )
        )
    return validate_equipment(
        dict(
            schema_version=1,
            hardware_validated=True,
            calibration_id="default_auto",
            robot_id="dsr01",
            robot_model="m0609",
            tool_name="Tool_Weight",
            tcp_name="GripperDA_v1",
            paper_mm=dict(width=297.0, height=210.0),
            paper_origin_base_mm=[460.0, 150.0, 238.0],
            paper_x_axis=[0.0, -1.0, 0.0],
            paper_y_axis=[-1.0, 0.0, 0.0],
            plane_abc=[0.0, 0.0, 238.0],
            orientation_deg=[0.0, 180.0, 0.0],
            pen_slots={
                "PEN_1": dict(pose=[567.0, 42.0, 366.0, 90.0, 180.0, 90.0], z_offset_mm=13.5),
                "PEN_2": dict(pose=[568.0, 11.0, 366.0, 95.0, 180.0, 95.0], z_offset_mm=13.5),
                "PEN_3": dict(pose=[568.0, -19.0, 366.0, 92.0, 180.0, 92.0], z_offset_mm=13.5),
            },
            limits_base_mm=[[-1000.0, 1000.0], [-1000.0, 1000.0], [0.0, 1000.0]],
            travel_z_mm=480.0,
            group_lift_mm=15.0,
            stroke_lift_mm=4.0,
            slot_approach_mm=100.0,
            travel_velocity=80.0,
            travel_acceleration=80.0,
            draw_velocity=25.0,
            draw_acceleration=25.0,
            pick_velocity=25.0,
            pick_acceleration=25.0,
            probe_velocity=5.0,
            probe_acceleration=5.0,
            joint_velocity=60.0,
            joint_acceleration=60.0,
            acceleration=80.0,
            motion_timeout_sec=120.0,
            use_spline=True,
            spline_validated=True,
            spline_max_points=80,
            corner_angle_deg=35.0,
            home_joints=[0.0, 0.0, 90.0, 0.0, 90.0, 0.0],
            ready_offset=[0.0, 0.0, -100.0, 0.0, 0.0, 0.0],
            stick_grip_rz_offset_deg=-45.0,
            auto_calibrate_9pt=True,
            calibrate_inset_mm=40.0,
            gripper=dict(
                grip_output=1, release_output=2, grip_input=None, release_input=None
            ),
        )
    )


def import_reference(plane_path, pens_path, stick_path=None):
    """참고 9점 보정과 펜 슬롯을 즉시 실행 가능한 프로필로 변환합니다."""
    plane = json.loads(Path(plane_path).read_text())
    pens = json.loads(Path(pens_path).read_text())
    points = [finite_vector(p, 6, "기존 보정점") for p in plane["points"]]
    if len(points) != 9 or len(pens) != 3:
        raise ValueError("9점 보정과 펜 슬롯 3개가 필요합니다.")
    stick_pose = None
    if stick_path is not None:
        stick_pose = list(finite_vector(json.loads(Path(stick_path).read_text())[:6], 6, "기준 막대 위치"))
    a, b, c = finite_vector([plane["a"], plane["b"], plane["c"]], 3, "평면")
    cx = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
    cy = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
    ox, oy = cx + 105.0, cy + 148.5
    max_z = max(p[2] for p in points)
    max_pen_z = max(float(p[2]) for p in pens)
    if stick_pose is not None:
        max_pen_z = max(max_pen_z, stick_pose[2])
    return dict(
        schema_version=1,
        hardware_validated=True,
        calibration_id="auto_local",
        robot_id="dsr01",
        robot_model="m0609",
        tool_name="Tool_Weight",
        tcp_name="GripperDA_v1",
        paper_mm=dict(width=297.0, height=210.0),
        paper_origin_base_mm=[ox, oy, a * ox + b * oy + c],
        paper_x_axis=[0.0, -1.0, 0.0],
        paper_y_axis=[-1.0, 0.0, 0.0],
        plane_abc=[a, b, c],
        orientation_deg=list(points[0][3:]),
        pen_slots={
            pen: dict(pose=list(finite_vector(p, 6, "펜 슬롯")), z_offset_mm=13.5)
            for pen, p in zip(PENS, pens)
        },
        stick_pose=stick_pose,
        calibration_points=[list(p) for p in points],
        limits_base_mm=[[-1000.0, 1000.0], [-1000.0, 1000.0], [0.0, 1000.0]],
        travel_z_mm=max(max_z + 45.0, max_pen_z + 110.0),
        group_lift_mm=15.0,
        stroke_lift_mm=4.0,
        slot_approach_mm=100.0,
        travel_velocity=80.0,
        travel_acceleration=80.0,
        draw_velocity=25.0,
        draw_acceleration=25.0,
        pick_velocity=25.0,
        pick_acceleration=25.0,
        probe_velocity=5.0,
        probe_acceleration=5.0,
        joint_velocity=60.0,
        joint_acceleration=60.0,
        acceleration=80.0,
        motion_timeout_sec=120.0,
        use_spline=True,
        spline_validated=True,
        spline_max_points=80,
        corner_angle_deg=35.0,
        home_joints=[0.0, 0.0, 90.0, 0.0, 90.0, 0.0],
        ready_offset=[0.0, 0.0, -100.0, 0.0, 0.0, 0.0],
        stick_grip_rz_offset_deg=-45.0,
        auto_calibrate_9pt=True,
        calibrate_inset_mm=40.0,
        gripper=dict(
            grip_output=1, release_output=2, grip_input=None, release_input=None
        ),
        note="로컬 캘리브레이션 파일 기반 자동 생성 프로필 (draw_image_standalone 동일 파라미터)",
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="기존 보정 백업을 검증 전 후보 프로필로 변환"
    )
    parser.add_argument("--plane", required=True, type=Path)
    parser.add_argument("--pens", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = import_reference(args.plane, args.pens)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print("검증 전 후보 프로필 저장:", args.output)


if __name__ == "__main__":
    main()
