"""draw_image_standalone과 동일한 모션 시퀀스·속도·리프트·스플라인으로 DrawingPlan을 실행합니다."""

import inspect
import math
import os
from pathlib import Path
import time
from .calibration_probe import DEFAULT_HOME_JOINTS, run_pre_drawing_calibration
from .paper_transform import drawing_pose


class DrawingCancelled(Exception):
    pass


class ExternalForceDetected(Exception):
    """외력 감지 즉시 정지 예외입니다. 자동 홈 이동을 수행하지 않습니다."""


def execution_strokes(plan, start_stroke_id=1):
    strokes = plan["strokes"]
    if type(start_stroke_id) is not int or not 1 <= start_stroke_id <= len(strokes):
        raise ValueError("재개 획 번호가 잘못되었습니다.")
    if [s["stroke_id"] for s in strokes] != list(range(1, len(strokes) + 1)):
        raise ValueError("획 순서가 잘못되었습니다.")
    return strokes[start_stroke_id - 1 :]


def split_at_corners(points, angle_deg=35.0):
    """참고 draw_stroke_group의 모서리 분할만 재사용합니다. 좌표는 수정하지 않습니다."""
    if len(points) < 3:
        return [points]
    parts = []
    current = points[:2]
    for i in range(1, len(points) - 1):
        a = [points[i][k] - points[i - 1][k] for k in (0, 1)]
        b = [points[i + 1][k] - points[i][k] for k in (0, 1)]
        na, nb = math.hypot(*a), math.hypot(*b)
        corner = (
            na > 1e-6
            and nb > 1e-6
            and math.degrees(
                math.acos(
                    max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (na * nb)))
                )
            )
            >= angle_deg
        )
        if corner:
            parts.append(current)
            current = [points[i], points[i + 1]]
        else:
            current.append(points[i + 1])
    parts.append(current)
    return parts


def motion_chunks(poses, settings):
    if not settings.get("use_spline"):
        return [[p] for p in poses[1:]]
    chunks = []
    for segment in split_at_corners(poses, settings.get("corner_angle_deg", 35.0)):
        targets = segment[1:]
        count = settings.get("spline_max_points", 80)
        chunks.extend(targets[i : i + count] for i in range(0, len(targets), count))
    return chunks


def validate_execution(plan, adapter):
    settings = adapter.settings
    if plan["paper_mm"] != settings["paper_mm"]:
        raise ValueError("계획의 용지 방향과 실제 보정 프로필이 다릅니다.")
    for info in settings["pen_slots"].values():
        adapter.validate(info["pose"])
        approach = list(info["pose"])
        approach[2] += settings["slot_approach_mm"]
        adapter.validate(approach)
        if approach[2] > settings["travel_z_mm"]:
            raise ValueError("슬롯 접근 높이보다 안전 이동 높이가 낮습니다.")
    for stroke in execution_strokes(plan):
        for point in stroke["points_mm"]:
            pose = drawing_pose(point, stroke["pen_id"], settings)
            adapter.validate(pose)
            pose[2] += settings["stroke_lift_mm"]
            adapter.validate(pose)
            if pose[2] > settings["travel_z_mm"]:
                raise ValueError("그림 영역의 이격 높이가 안전 이동 높이보다 높습니다.")


class MotionRunner:
    def __init__(self, adapter, session, cancelled, *, job_id="", force_guard=None):
        self.adapter, self.session, self.cancelled = adapter, session, cancelled
        self.job_id = job_id
        self.force_guard = force_guard
        self.motion_context = {"pen_idx": 0, "stroke_idx": 0, "point_idx": 0, "held_item": ""}
        self._resumed_from_home = False

    def check_cancel(self):
        if self.cancelled() or self.session.state in ("STOPPING", "STOPPED"):
            self.session.request_stop()
            raise DrawingCancelled("사용자 작업중단")
        if self.session.state == "FAILED":
            raise RuntimeError("실행 문맥이 실패했습니다.")

    def _run_park_motion(self, start_fn):
        start_fn()
        deadline = time.monotonic() + self.adapter.settings.get("motion_timeout_sec", 60.0)
        while time.monotonic() < deadline:
            self.check_cancel()
            if self.adapter.motion_complete():
                return
            time.sleep(0.03)
        raise RuntimeError("일시정지 홈 복귀 시간 초과")

    def _park_if_pausing(self):
        if self.session.state != "PAUSING":
            return
        if self.adapter.held_pen is not None:
            settings = self.adapter.settings
            pose = self.adapter.current_pose()
            if pose[2] < settings["travel_z_mm"] - 0.2:
                lifted = list(pose)
                lifted[2] = settings["travel_z_mm"]
                self._run_park_motion(
                    lambda: self.adapter.begin_motion([lifted], settings.get("pick_velocity", 25.0))
                )
            if hasattr(self.adapter, "move_joint"):
                j_vel = settings.get("joint_velocity", 60.0)
                j_acc = settings.get("joint_acceleration", 60.0)
                home = settings.get("home_joints", DEFAULT_HOME_JOINTS)
                self._run_park_motion(
                    lambda: self.adapter.move_joint(home, velocity=j_vel, acceleration=j_acc)
                )
            self._resumed_from_home = True
        else:
            self._resumed_from_home = False
        self.session.mark_parked()

    def wait_running(self):
        while True:
            self.check_cancel()
            if self.session.state == "PAUSING":
                self._park_if_pausing()
            if self.session.wait_running(0.02):
                return

    def commit(self, callback):
        while True:
            self.wait_running()
            with self.session.condition:
                if self.session.state == "RUNNING":
                    return callback()

    def _save_force_checkpoint(self, actual_pose, tool_force):
        if self.force_guard is None:
            return
        try:
            from art_state_store import RobotStateStore
        except ImportError:
            return
        wp = self.force_guard.buffer.build_recovery_waypoint(
            fault_actual_pose=actual_pose,
            fault_tool_force=tool_force,
            force_limit_n=self.force_guard.force_limit_n,
        )
        if wp is None or not self.job_id:
            return
        a4_root = next((p.parent for p in Path(__file__).resolve().parents if p.name == "ros2_ws"), Path.cwd())
        db_path = Path(os.environ.get("ART_STATE_DB_PATH", str(a4_root / "data/art_state.db")))
        store = RobotStateStore(db_path)
        try:
            store.save_recovery_checkpoint(**wp.to_db_kwargs(job_id=self.job_id))
        finally:
            store.close()

    def _check_external_force(self, target_pose):
        if self.force_guard is None or not hasattr(self.adapter, "read_tool_force"):
            return
        force = self.adapter.read_tool_force(0)
        ctx = self.motion_context
        exceeded = self.force_guard.record_tick(
            pen_idx=ctx["pen_idx"],
            stroke_idx=ctx["stroke_idx"],
            point_idx=ctx["point_idx"],
            held_item_name=ctx["held_item"],
            target_pose=target_pose,
            actual_pose=target_pose,
            tool_force=force,
        )
        if exceeded:
            actual = self.adapter.current_pose() if hasattr(self.adapter, "current_pose") else target_pose
            self._save_force_checkpoint(actual, force)
            raise ExternalForceDetected(
                f"외력 감지 즉시 정지 (stroke={ctx['stroke_idx']}, point={ctx['point_idx']})"
            )

    def _wait_motion_complete(self, target_pose=None):
        elapsed = 0.0
        last_force_check = 0.0
        previous = time.monotonic()
        while True:
            self.check_cancel()
            now = time.monotonic()
            if self.session.state in ("RUNNING", "PAUSING"):
                elapsed += now - previous
                if now - last_force_check >= 0.1:
                    self._check_external_force(target_pose or [0.0] * 6)
                    last_force_check = now
                if self.adapter.held_pen is not None:
                    grip_input = self.adapter.settings["gripper"].get("grip_input")
                    if grip_input is not None and self.adapter.read_input(grip_input) != 1:
                        raise RuntimeError("그리기 중 펜 파지 확인이 해제되었습니다.")
                complete = self.adapter.motion_complete()
                with self.session.condition:
                    if complete and self.session.complete_motion():
                        return
                if elapsed > self.adapter.settings["motion_timeout_sec"]:
                    raise RuntimeError("모션 완료 확인 시간 초과")
            previous = time.monotonic()
            time.sleep(0.015)

    def move(self, poses, velocity, acceleration=None, mod=0):
        params = inspect.signature(self.adapter.begin_motion).parameters
        supports_ext = "acceleration" in params and "mod" in params
        self.wait_running()
        if self._resumed_from_home:
            self._resumed_from_home = False
            if mod == 0 and poses:
                settings = self.adapter.settings
                above = list(poses[0])
                above[2] = settings["travel_z_mm"]
                self.move([above], settings.get("travel_velocity", 80.0))
                self.move([poses[0]], settings.get("pick_velocity", 25.0))
        while True:
            self.wait_running()
            with self.session.condition:
                if self.session.state != "RUNNING":
                    continue
                if not supports_ext:
                    if mod != 0:
                        raise RuntimeError("상대 이동을 지원하지 않는 어댑터입니다.")
                    action = lambda: self.adapter.begin_motion(poses, velocity)
                else:
                    action = lambda: self.adapter.begin_motion(
                        poses, velocity, acceleration=acceleration, mod=mod
                    )
                self.session.submit_motion(action)
                break
        self._wait_motion_complete(poses[-1] if mod == 0 and poses else None)

    def move_joint(self, joints, velocity=None, acceleration=None):
        while True:
            self.wait_running()
            self._resumed_from_home = False
            with self.session.condition:
                if self.session.state != "RUNNING":
                    continue
                self.session.submit_motion(
                    lambda: self.adapter.move_joint(
                        joints, velocity=velocity, acceleration=acceleration
                    )
                )
                break
        self._wait_motion_complete()

    def travel_to(self, target):
        settings = self.adapter.settings
        self.wait_running()
        current = self.adapter.current_pose()
        raised = list(current)
        raised[2] = settings["travel_z_mm"]
        self.move([raised], settings["travel_velocity"])
        across = list(target)
        across[2] = settings["travel_z_mm"]
        self.move([across], settings["travel_velocity"])
        self.move([target], settings["pick_velocity"])


def execute(
    plan,
    adapter,
    start_stroke_id=1,
    *,
    session=None,
    cancelled=lambda: False,
    feedback=lambda *args: None
):
    adapter.require_ready()
    if session is None:
        raise RuntimeError("동일 실행을 보존할 LiveMotionSession이 필요합니다.")
    validate_execution(plan, adapter)
    from .pen_controller import PenController

    force_guard = None
    if hasattr(adapter, "read_tool_force"):
        try:
            from art_state_store import ExternalForceGuard

            force_guard = ExternalForceGuard(
                force_limit_n=float(adapter.settings.get("external_force_limit_n", 20.0))
            )
        except ImportError:
            force_guard = None

    runner = MotionRunner(
        adapter,
        session,
        cancelled,
        job_id=str(plan.get("job_id", "")),
        force_guard=force_guard,
    )
    pens = PenController(adapter, runner)
    calibrated = run_pre_drawing_calibration(adapter, runner, pens)

    completed = start_stroke_id - 1
    settings = adapter.settings
    l_vel = settings.get("travel_velocity", 80.0)
    l_acc = settings.get("travel_acceleration", settings.get("acceleration", 80.0))
    p_vel = settings.get("pick_velocity", 25.0)
    p_acc = settings.get("pick_acceleration", settings.get("acceleration", 25.0))
    d_vel = settings.get("draw_velocity", 25.0)
    d_acc = settings.get("draw_acceleration", settings.get("acceleration", 25.0))
    group_lift = settings.get("group_lift_mm", 15.0)
    stroke_lift = settings.get("stroke_lift_mm", 4.0)

    last_pose = None
    for stroke in execution_strokes(plan, start_stroke_id):
        runner.check_cancel()
        prev_pen = adapter.held_pen
        poses = [
            drawing_pose(p, stroke["pen_id"], settings) for p in stroke["points_mm"]
        ]
        if prev_pen != stroke["pen_id"]:
            if prev_pen is not None and last_pose is not None:
                group_end = list(last_pose)
                group_end[2] += group_lift
                runner.move([group_end], l_vel, l_acc)
            pens.select(stroke["pen_id"])
            group_start = list(poses[0])
            group_start[2] += group_lift
            runner.move([group_start], l_vel, l_acc)

        runner.motion_context.update(
            pen_idx=int(stroke["pen_id"].split("_")[1]) - 1 if "_" in stroke["pen_id"] else 0,
            stroke_idx=stroke["stroke_id"],
            point_idx=0,
            held_item=stroke["pen_id"],
        )
        runner.commit(
            lambda: feedback(
                "STROKE_STARTED", stroke["stroke_id"], stroke["pen_id"]
            )
        )
        first = list(poses[0])
        first[2] += stroke_lift
        runner.move([first], l_vel, l_acc)
        runner.move([poses[0]], p_vel, p_acc)
        for pt_idx, chunk in enumerate(motion_chunks(poses, settings), start=1):
            runner.motion_context["point_idx"] = pt_idx
            runner.move(chunk, d_vel, d_acc)
        lifted = list(poses[-1])
        lifted[2] += stroke_lift
        runner.move([lifted], l_vel, l_acc)
        last_pose = poses[-1]

        def commit_stroke():
            feedback("STROKE_COMPLETED", stroke["stroke_id"], stroke["pen_id"])

        runner.commit(commit_stroke)
        completed = stroke["stroke_id"]

    if last_pose is not None and adapter.held_pen is not None:
        group_end = list(last_pose)
        group_end[2] += group_lift
        runner.move([group_end], l_vel, l_acc)
    pens.return_current()

    if calibrated:
        j_vel = settings.get("joint_velocity", 60.0)
        j_acc = settings.get("joint_acceleration", 60.0)
        runner.move_joint(settings.get("home_joints", DEFAULT_HOME_JOINTS), j_vel, j_acc)
        pens.gripper.off(runner)

    return completed
