"""실물 명령 없이 새 실행기의 좌표·펜 보존과 같은 모션 재개를 검증합니다."""

import copy
import json
import threading
import time
import pytest
from art_drawing_controller.equipment_settings import (
    validate_equipment,
    load_equipment_settings,
    profile_unchanged,
)
from art_drawing_controller.paper_transform import drawing_pose
from art_drawing_controller.stroke_executor import (
    execute,
    motion_chunks,
    validate_execution,
)
from art_drawing_controller.live_motion import LiveMotionSession


def settings():
    return dict(
        schema_version=1,
        hardware_validated=True,
        calibration_id="TEST_ONLY",
        robot_id="test",
        robot_model="m0609",
        tool_name="test",
        tcp_name="test",
        paper_mm=dict(width=297.0, height=210.0),
        paper_origin_base_mm=[0.0, 0.0, 0.0],
        paper_x_axis=[1.0, 0.0, 0.0],
        paper_y_axis=[0.0, 1.0, 0.0],
        plane_abc=[0.0, 0.0, 0.0],
        orientation_deg=[0.0, 180.0, 0.0],
        limits_base_mm=[[-100.0, 400.0], [-100.0, 400.0], [-10.0, 500.0]],
        travel_z_mm=250.0,
        stroke_lift_mm=4.0,
        slot_approach_mm=100.0,
        travel_velocity=80.0,
        draw_velocity=25.0,
        pick_velocity=25.0,
        acceleration=80.0,
        motion_timeout_sec=10.0,
        use_spline=False,
        spline_validated=False,
        pen_slots={
            p: dict(
                pose=[float(i * 20), -20.0, 100.0, 0.0, 180.0, 0.0], z_offset_mm=0.0
            )
            for i, p in enumerate(("PEN_1", "PEN_2", "PEN_3"))
        },
        gripper=dict(grip_output=1, release_output=2, grip_input=3, release_input=4),
    )


class RecordingAdapter:
    """생산 실행기에 주입하는 시험 전용 모션 관측기. 실물 어댑터로 사용하지 않습니다."""

    def __init__(self):
        self.settings = settings()
        self.held_pen = None
        self.pose = [0.0, 0.0, 250.0, 0.0, 180.0, 0.0]
        self.commands = []
        self.gripped = False
        self.paused = False
        self.progress = 0
        self.pending = None

    def require_ready(self):
        pass

    def validate(self, pose):
        assert len(pose) == 6
        for value, (lo, hi) in zip(pose, self.settings["limits_base_mm"]):
            assert lo <= value <= hi

    def at_pose(self, target):
        return self.pose == target

    def current_pose(self):
        return self.pose[:]

    def begin_motion(self, poses, velocity):
        self.commands.append(copy.deepcopy(poses))
        self.pending = poses[-1][:]
        self.progress = 0

    def motion_complete(self):
        if self.paused:
            return False
        self.progress += 1
        if self.progress < 4:
            return False
        self.pose = self.pending[:]
        return True

    def read_input(self, index):
        return int(self.gripped if index == 3 else not self.gripped)

    def set_output(self, index, value):
        if value:
            self.gripped = index == 1

    def pen_up_confirmed(self):
        return self.pose[2] >= 4 and (
            self.gripped if self.held_pen else not self.gripped
        )

    def pause(self, inflight):
        self.paused = True
        return tuple(self.pose)

    def resume(self, hold, inflight):
        assert tuple(self.pose) == hold
        self.paused = False

    def stop(self):
        self.paused = False
        self.pose[2] = 250.0
        return True


def test_profile_rejects_unverified_and_detects_changes(tmp_path):
    data = settings()
    validate_equipment(data)
    for key, value in [
        ("hardware_validated", False),
        ("limits_base_mm", None),
        ("use_spline", True),
    ]:
        invalid = copy.deepcopy(data)
        invalid[key] = value
        with pytest.raises(ValueError):
            validate_equipment(invalid)
    invalid = copy.deepcopy(data)
    invalid["gripper"]["grip_input"] = None
    with pytest.raises(ValueError):
        validate_equipment(invalid)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(data))
    loaded = load_equipment_settings(path)
    assert profile_unchanged(loaded)
    path.write_text(json.dumps(data) + " ")
    assert not profile_unchanged(loaded)


def test_coordinates_and_spline_do_not_rescale_or_lose_targets():
    data = settings()
    data["paper_x_axis"] = [0.0, -1.0, 0.0]
    data["paper_y_axis"] = [-1.0, 0.0, 0.0]
    data["paper_origin_base_mm"] = [300.0, 200.0, 0.0]
    data["plane_abc"] = [0.1, 0.2, 10.0]
    data["pen_slots"]["PEN_2"]["z_offset_mm"] = 2.0
    assert drawing_pose([20.0, 30.0], "PEN_2", data) == [
        270.0,
        180.0,
        75.0,
        0.0,
        180.0,
        0.0,
    ]
    poses = [[float(i), 0.0, 0.0, 0.0, 180.0, 0.0] for i in range(182)]
    chunks = motion_chunks(poses, dict(use_spline=True, spline_max_points=80))
    assert [p for c in chunks for p in c] == poses[1:]
    assert max(map(len, chunks)) == 80


def test_production_executor_preserves_same_motion_through_pause():
    adapter = RecordingAdapter()
    events = []
    errors = []
    plan = dict(
        paper_mm=adapter.settings["paper_mm"],
        strokes=[
            dict(
                stroke_id=1,
                pen_id="PEN_2",
                layer="artwork",
                points_mm=[[20.0, 20.0], [30.0, 20.0], [40.0, 20.0]],
            ),
            dict(
                stroke_id=2,
                pen_id="PEN_1",
                layer="calligraphy",
                points_mm=[[50.0, 180.0], [60.0, 180.0]],
            ),
        ],
    )
    original = copy.deepcopy(plan)
    session = LiveMotionSession("TEST", "EXEC", adapter, lambda *a: None)

    def worker():
        try:
            execute(
                plan,
                adapter,
                session=session,
                feedback=lambda *args: events.append(args),
            )
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if adapter.pending == [30.0, 20.0, 0.0, 0.0, 180.0, 0.0] and session.inflight:
            break
        time.sleep(0.005)
    else:
        pytest.fail("획 내부 모션에 도달하지 못했습니다.")
    assert session.control("EXEC", "PAUSE", "P1")[0]
    count = len(adapter.commands)
    progress = adapter.progress
    time.sleep(0.12)
    assert adapter.progress == progress and len(adapter.commands) == count
    assert not any(e[0] == "STROKE_COMPLETED" for e in events)
    assert session.control("EXEC", "RESUME", "R1")[0]
    thread.join(8)
    assert not thread.is_alive() and not errors
    assert (
        sum(
            command == [[30.0, 20.0, 0.0, 0.0, 180.0, 0.0]]
            for command in adapter.commands
        )
        == 1
    )
    assert [(e[1], e[2]) for e in events if e[0] == "STROKE_COMPLETED"] == [
        (1, "PEN_2"),
        (2, "PEN_1"),
    ]
    assert plan == original and adapter.held_pen is None and adapter.pen_up_confirmed()
    wrong = copy.deepcopy(plan)
    wrong["paper_mm"] = dict(width=210.0, height=297.0)
    with pytest.raises(ValueError):
        validate_execution(wrong, adapter)


def test_doosan_motion_payloads_match_installed_driver_contract():
    srv = pytest.importorskip("dsr_msgs2.srv")
    from art_drawing_controller.doosan_adapter import DoosanAdapter

    adapter = DoosanAdapter()
    adapter.settings = settings()
    adapter.settings.update(use_spline=True, spline_validated=True)
    calls = []

    class ContractRecorder:
        def call(self, key, deadline, **fields):
            typ = {"line": srv.MoveLine, "spline": srv.MoveSplineTask}[key]
            request = typ.Request(**fields)
            calls.append((key, request))

    adapter.control = ContractRecorder()
    adapter.require_ready = lambda: None
    adapter.begin_motion([[20.0, 20.0, 0.0, 0.0, 180.0, 0.0]], 25.0)
    adapter.begin_motion(
        [[30.0, 20.0, 0.0, 0.0, 180.0, 0.0], [40.0, 20.0, 0.0, 0.0, 180.0, 0.0]], 25.0
    )
    assert calls[0][1].sync_type == 1 and calls[0][1].pos[0] == 20.0
    assert calls[1][1].sync_type == 1 and calls[1][1].pos_cnt == 2
    assert calls[1][1].pos[1].data[0] == 40.0 and calls[1][1].opt == 1


def test_cancel_paused_incomplete_stroke_never_commits_it():
    from art_drawing_controller.stroke_executor import DrawingCancelled
    adapter=RecordingAdapter();events=[];errors=[]
    plan=dict(paper_mm=adapter.settings['paper_mm'],strokes=[dict(stroke_id=1,pen_id='PEN_1',layer='artwork',points_mm=[[20.,20.],[30.,20.]])])
    session=LiveMotionSession('TEST','EXEC',adapter,lambda *a:None)
    def worker():
        try:execute(plan,adapter,session=session,feedback=lambda *args:events.append(args))
        except DrawingCancelled:errors.append('cancelled')
    thread=threading.Thread(target=worker);thread.start();deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        if adapter.pending==[30.,20.,0.,0.,180.,0.] and session.inflight:break
        time.sleep(.005)
    else:pytest.fail('획 내부 모션 대기 시간 초과')
    assert session.control('EXEC','PAUSE','P')[0]
    session.request_stop();thread.join(3)
    assert errors==['cancelled'] and not thread.is_alive()
    assert not any(e[0]=='STROKE_COMPLETED' for e in events)
    assert session.cancel() and adapter.pose[2]==250.
    assert not session.control('EXEC','RESUME','R')[0]
