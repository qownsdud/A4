"""draw_image_standalone과 동일한 캘리브레이션·포스 접촉·그리기 모션 시퀀스를 검증합니다."""

import copy
from art_drawing_controller.equipment_settings import (
    load_default_equipment_settings,
    validate_equipment,
)
from art_drawing_controller.live_motion import LiveMotionSession
from art_drawing_controller.stroke_executor import execute


class FakeStandaloneAdapter:
    def __init__(self):
        self.settings = validate_equipment(
            dict(
                schema_version=1,
                hardware_validated=True,
                calibration_id="TEST_STANDALONE",
                robot_id="dsr01",
                robot_model="m0609",
                tool_name="Tool_Weight",
                tcp_name="GripperDA_v1",
                paper_mm=dict(width=297.0, height=210.0),
                paper_origin_base_mm=[460.0, 150.0, 100.0],
                paper_x_axis=[0.0, -1.0, 0.0],
                paper_y_axis=[-1.0, 0.0, 0.0],
                plane_abc=[0.0, 0.0, 100.0],
                orientation_deg=[0.0, 180.0, 0.0],
                pen_slots={
                    "PEN_1": dict(pose=[567.0, 42.0, 366.0, 90.0, 180.0, 90.0], z_offset_mm=13.5),
                    "PEN_2": dict(pose=[568.0, 11.0, 366.0, 95.0, 180.0, 95.0], z_offset_mm=13.5),
                    "PEN_3": dict(pose=[568.0, -19.0, 366.0, 92.0, 180.0, 92.0], z_offset_mm=13.5),
                },
                stick_pose=[568.0, -50.0, 366.0, 90.0, 180.0, 90.0],
                calibration_points=[
                    [250.0 + 100.0 * ix, 50.0 + 100.0 * iy, 100.0, 0.0, 180.0, 0.0]
                    for ix in range(3)
                    for iy in range(3)
                ],
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
                motion_timeout_sec=30.0,
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
        self.control = object()
        self.held_pen = None
        self.pose = [0.0, 0.0, 600.0, 0.0, 180.0, 0.0]
        self.outputs = {}
        self.tool_set = False
        self.joint_calls = []
        self.motion_calls = []

    def require_ready(self):
        pass

    def validate(self, pose):
        return list(pose)

    def set_tool_and_tcp(self):
        self.tool_set = True

    def set_output(self, index, value):
        self.outputs[index] = value

    def at_pose(self, target):
        return False

    def current_pose(self):
        return list(self.pose)

    def move_joint(self, joints, velocity=None, acceleration=None):
        self.joint_calls.append((list(joints), velocity, acceleration))
        # 홈 위치 이동 시 기준 막대 측정 시작 높이(600mm)로 복귀
        self.pose = [350.0, 150.0, 600.0, 0.0, 180.0, 0.0]

    def begin_motion(self, poses, velocity, acceleration=None, mod=0):
        self.motion_calls.append((copy.deepcopy(poses), velocity, acceleration, mod))
        if mod == 1:
            for i in range(6):
                self.pose[i] += poses[-1][i]
        else:
            self.pose = list(poses[-1])

    def motion_complete(self):
        return True

    def read_tool_force_z(self, ref=0):
        # 9점(z<=101.0) 또는 기준 막대(z<=496.0)에 닿으면 접촉력 발생 시뮬레이션
        floor_z = 496.0 if self.pose[2] > 200.0 else (101.0 + 0.01 * (self.pose[0] - 350.0))
        if self.pose[2] <= floor_z:
            return 3.5
        return 0.0

    def pen_up_confirmed(self):
        return True


def test_default_settings_match_standalone_parameters():
    cfg = load_default_equipment_settings()
    assert cfg["travel_velocity"] == 80.0
    assert cfg["draw_velocity"] == 25.0
    assert cfg["pick_velocity"] == 25.0
    assert cfg["probe_velocity"] == 5.0
    assert cfg["joint_velocity"] == 60.0
    assert cfg["group_lift_mm"] == 15.0
    assert cfg["stroke_lift_mm"] == 4.0
    assert cfg["slot_approach_mm"] == 100.0
    for pen in ("PEN_1", "PEN_2", "PEN_3"):
        assert cfg["pen_slots"][pen]["z_offset_mm"] == 13.5


def test_execute_runs_9pt_calibration_stick_probe_and_standalone_drawing(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    adapter = FakeStandaloneAdapter()
    events = []
    plan = dict(
        paper_mm=adapter.settings["paper_mm"],
        strokes=[
            dict(
                stroke_id=1,
                pen_id="PEN_1",
                layer="artwork",
                points_mm=[[10.0, 10.0], [20.0, 10.0], [30.0, 10.0]],
            ),
            dict(
                stroke_id=2,
                pen_id="PEN_2",
                layer="artwork",
                points_mm=[[40.0, 20.0], [50.0, 20.0]],
            ),
        ],
    )
    session = LiveMotionSession("J1", "E1", adapter, lambda *a: None)
    completed = execute(
        plan, adapter, session=session, feedback=lambda *args: events.append(args)
    )
    assert completed == 2
    assert adapter.tool_set is True
    # 초기 홈 + 9점 후 홈 + 기준막대 측정 홈 + 최종 홈 = 4회
    assert len(adapter.joint_calls) == 4
    assert adapter.joint_calls[-1] == ([0.0, 0.0, 90.0, 0.0, 90.0, 0.0], 60.0, 60.0)
    # 9점 캘리브레이션 기울기 a ≈ 0.01 반영 확인 (0.5mm 탐색 스텝 양자화 오차 포함)
    assert abs(adapter.settings["plane_abc"][0] - 0.01) < 2e-3
    # 기준 막대 집기 시 rz -45도 오프셋 적용 확인
    stick_pick_targets = [
        poses[0] for poses, vel, _acc, mod in adapter.motion_calls
        if mod == 0 and vel == 25.0 and abs(poses[0][1] - (-50.0)) < 1e-6
    ]
    assert stick_pick_targets and stick_pick_targets[0][5] == 45.0
    # 그리기 속도 25/25 및 완료 후 그리퍼 OFF(0, 0) 확인
    draw_calls = [c for c in adapter.motion_calls if c[1] == 25.0 and c[2] == 25.0 and c[3] == 0]
    assert len(draw_calls) >= 2
    assert adapter.outputs == {1: 0, 2: 0}
    assert [(e[0], e[1], e[2]) for e in events if e[0] == "STROKE_COMPLETED"] == [
        ("STROKE_COMPLETED", 1, "PEN_1"),
        ("STROKE_COMPLETED", 2, "PEN_2"),
    ]
