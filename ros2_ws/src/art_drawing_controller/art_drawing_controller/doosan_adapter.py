"""참고 드로잉 코드의 이동 기능만 ROS 서비스로 연결합니다. 이미지 처리·접촉 탐색은 없습니다."""

import math
import threading
import time
from .equipment_settings import validate_equipment, profile_unchanged
from .motion_safety import validate_pose
from .doosan_motion_control import DoosanMotionControl


class DriverAlarmLatch:
    """제어기 오류 알람을 스레드 안전하게 래치합니다."""

    def __init__(self):
        self._lock = threading.Lock()
        self.generation = 0
        self.reason = ""

    def receive(self, message):
        if getattr(message, "level", 0) < 3 and not (
            getattr(message, "group", 0) == 5 and getattr(message, "level", 0) >= 2
        ):
            return
        with self._lock:
            self.generation += 1
            self.reason = (
                f"제어기 알람 level={message.level}, group={message.group}, "
                f"code={message.code}: {message.msg1} {message.msg2} {message.msg3}"
            )[:400]

    def snapshot(self):
        with self._lock:
            return self.generation, self.reason

    def clear(self):
        with self._lock:
            self.reason = ""


class DoosanAdapter:
    def __init__(self, node=None, settings=None):
        self.node, self.settings = node, settings
        self.held_pen = None
        self.held_stick_pose = None
        self._target = None
        self._motion_kind = "task"
        self.control = None
        self.alarm = DriverAlarmLatch()
        if node is None or settings is None:
            return
        validate_equipment(settings)
        self.control = DoosanMotionControl(
            node,
            ready=self.equipment_ready,
            stop_and_lift=self._stop_and_lift,
            motion_complete=self.motion_complete,
            prefix=f"/{settings['robot_id']}/dsr_controller2",
        )
        from dsr_msgs2.srv import (
            MoveLine,
            MoveJoint,
            MoveSplineTask,
            SetCtrlBoxDigitalOutput,
            GetCtrlBoxDigitalInput,
            GetToolForce,
            GetCurrentTool,
            GetCurrentTcp,
            SetCurrentTool,
            SetCurrentTcp,
            GetRobotSystem,
        )
        from rclpy.callback_groups import ReentrantCallbackGroup

        services = dict(
            line=(MoveLine, "motion/move_line"),
            joint=(MoveJoint, "motion/move_joint"),
            spline=(MoveSplineTask, "motion/move_spline_task"),
            output=(SetCtrlBoxDigitalOutput, "io/set_ctrl_box_digital_output"),
            input=(GetCtrlBoxDigitalInput, "io/get_ctrl_box_digital_input"),
            force=(GetToolForce, "aux_control/get_tool_force"),
            tool=(GetCurrentTool, "tool/get_current_tool"),
            tcp=(GetCurrentTcp, "tcp/get_current_tcp"),
            set_tool=(SetCurrentTool, "tool/set_current_tool"),
            set_tcp=(SetCurrentTcp, "tcp/set_current_tcp"),
            system=(GetRobotSystem, "system/get_robot_system"),
        )
        prefix = f"/{settings['robot_id']}/dsr_controller2/"
        for key, (typ, suffix) in services.items():
            self.control.types[key] = typ
            self.control.clients[key] = node.create_client(
                typ, prefix + suffix, callback_group=ReentrantCallbackGroup()
            )
        try:
            from dsr_msgs2.msg import RobotError

            node.create_subscription(
                RobotError,
                f"/{settings['robot_id']}/error",
                self.alarm.receive,
                100,
                callback_group=ReentrantCallbackGroup(),
            )
        except ImportError:
            pass

    def _require_initialized(self):
        if self.control is None or self.settings is None:
            raise RuntimeError("실물 프로필·M0609·RG2 준비 검증이 필요합니다.")
        _, alarm_reason = self.alarm.snapshot()
        if alarm_reason:
            raise RuntimeError(alarm_reason)

    def require_ready(self):
        self._require_initialized()
        if not self.equipment_ready():
            raise RuntimeError("장비 프로필·Tool·TCP·연결 상태를 확인할 수 없습니다.")

    def equipment_ready(self):
        if self.control is None:
            return False
        deadline = time.monotonic() + 2.0
        return self.control.call("system", deadline).robot_system == 0

    def preflight(self):
        self.require_ready()
        if self.held_pen is not None or self.held_stick_pose is not None:
            self.return_pen_and_home()
        pose = self.control.stationary(time.monotonic() + 3.0)
        self.validate(pose)
        io = self.settings["gripper"]
        if io.get("grip_input") is None or io.get("release_input") is None:
            self.set_output(io["grip_output"], 0)
            self.set_output(io["release_output"], 1)
            time.sleep(0.5)
            return
        if (
            self.read_input(io["release_input"]) != 1
            or self.read_input(io["grip_input"]) != 0
        ):
            raise RuntimeError(
                "시작 시 빈 그리퍼의 열림 확인이 필요합니다. 이전 파지 상태를 추정하지 않습니다."
            )

    def validate(self, pose):
        if len(pose) != 6 or not all(math.isfinite(x) for x in pose):
            raise ValueError("유효한 6축 pose가 필요합니다.")
        validate_pose(pose[:3], self.settings["limits_base_mm"])
        return list(pose)

    def move(self, pose):
        # 이전 호출도 준비 검사 없이 실물을 움직이지 못하도록 유지합니다.
        self.require_ready()
        return self.begin_motion([pose], self.settings["travel_velocity"])

    def set_tool_and_tcp(self):
        self.require_ready()
        deadline = time.monotonic() + 3.0
        for key, value in (("set_tool", self.settings["tool_name"]), ("set_tcp", self.settings["tcp_name"])):
            try:
                self.control.call(key, deadline, name=value)
            except RuntimeError as exc:
                if not str(exc).startswith("DRIVER_REJECTED_"):
                    raise
                if self.node is not None:
                    self.node.get_logger().warning(
                        f"{key}({value}) 거부됨 — 기존 설정으로 계속 진행합니다: {exc}"
                    )

    def move_joint(self, joints, velocity=None, acceleration=None):
        self.require_ready()
        if len(joints) != 6 or not all(math.isfinite(x) for x in joints):
            raise ValueError("유효한 6축 관절 각도가 필요합니다.")
        vel = float(velocity if velocity is not None else self.settings.get("joint_velocity", 60.0))
        acc = float(acceleration if acceleration is not None else self.settings.get("joint_acceleration", 60.0))
        self._target = None
        self._motion_kind = "joint"
        deadline = time.monotonic() + 30.0
        self.control.call(
            "joint",
            deadline,
            pos=[float(v) for v in joints],
            vel=vel,
            acc=acc,
            time=0.0,
            radius=0.0,
            mode=0,
            blend_type=0,
            sync_type=1,
        )

    def read_tool_force(self, ref=0):
        if self.control is None:
            raise RuntimeError("제어기가 초기화되지 않았습니다.")
        _, alarm_reason = self.alarm.snapshot()
        if alarm_reason:
            raise RuntimeError(alarm_reason)
        deadline = time.monotonic() + 2.0
        res = self.control.call("force", deadline, ref=int(ref))
        vals = [float(v) for v in res.tool_force[:6]]
        if len(vals) != 6 or not all(math.isfinite(v) for v in vals):
            raise RuntimeError("6축 힘 센서 측정값이 유효하지 않습니다.")
        return vals

    def read_tool_force_z(self, ref=0):
        return self.read_tool_force(ref=ref)[2]

    def begin_motion(self, poses, velocity, acceleration=None, mod=0):
        self._require_initialized()
        if mod == 0:
            poses = [self.validate(p) for p in poses]
        else:
            if not poses or any(len(p) != 6 or not all(math.isfinite(x) for x in p) for p in poses):
                raise ValueError("유효한 6축 상대 pose가 필요합니다.")
            poses = [list(map(float, p)) for p in poses]
        if not poses:
            raise ValueError("빈 모션입니다.")
        self._target = tuple(poses[-1]) if mod == 0 else None
        self._motion_kind = "task" if mod == 0 else "rel"
        acc = float(acceleration if acceleration is not None else self.settings["acceleration"])
        deadline = time.monotonic() + 3.0
        fields = dict(
            vel=[float(velocity), 30.0],
            acc=[acc, 30.0],
            time=0.0,
            ref=0,
            mode=int(mod),
            sync_type=1,
        )
        if len(poses) == 1:
            self.control.call(
                "line", deadline, pos=poses[0], radius=0.0, blend_type=0, **fields
            )
        else:
            if mod != 0 or not self.settings.get("use_spline") or len(poses) > self.settings.get(
                "spline_max_points", 80
            ):
                raise ValueError("검증되지 않은 스플라인 호출입니다.")
            from std_msgs.msg import Float64MultiArray

            self.control.call(
                "spline",
                deadline,
                pos=[Float64MultiArray(data=p) for p in poses],
                pos_cnt=len(poses),
                opt=int(self.settings.get("spline_vel_opt", 0)),
                **fields,
            )

    def motion_complete(self):
        deadline = time.monotonic() + 3.0
        status = self.control.call("motion", deadline).status
        return status == 0

    def at_pose(self, target):
        """같은 목표로 이동을 생략할 때 현재 자세를 1회 관측해 비교합니다."""
        try:
            pose = self.current_pose()
        except RuntimeError:
            return False
        return self.control.same_pose(pose, target)

    def current_pose(self):
        return list(self.control.observed(time.monotonic() + 3.0)[0])

    def read_input(self, index):
        value = self.control.call("input", time.monotonic() + 2.0, index=index).value
        if value not in (0, 1):
            raise RuntimeError("잘못된 디지털 입력 상태입니다.")
        return value

    def set_output(self, index, value):
        self.control.call("output", time.monotonic() + 2.0, index=index, value=value)

    def pause(self, inflight):
        return self.control.pause(inflight)

    def resume(self, hold, inflight):
        return self.control.resume(hold, inflight)

    def stop(self):
        return self.control.stop()

    def _stop_and_lift(self):
        # 자동 슬롯 복귀·홈 이동·펜 해제를 하지 않습니다. 현재 파지를 유지해 수직 이격합니다.
        self.require_ready()
        pose = self.current_pose()
        self.validate(pose)
        if pose[2] >= self.settings["travel_z_mm"] - 0.2:
            return True
        target = list(pose)
        target[2] = self.settings["travel_z_mm"]
        self.begin_motion([target], self.settings["pick_velocity"])
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self.motion_complete():
                return True
            time.sleep(0.02)
        return False

    def return_pen_and_home(self):
        """작업 중단/예외 이후 들고 있는 펜을 슬롯에 반납하고 홈 위치로 복귀합니다."""
        from .pen_controller import PenController

        self.require_ready()
        adapter = self

        class _RecoverySession:
            state = "RUNNING"
            condition = threading.RLock()

        class _RecoveryRunner:
            session = _RecoverySession()

            @staticmethod
            def wait_running():
                return True

            @staticmethod
            def check_cancel():
                return None

            @staticmethod
            def _wait_done(timeout_sec=30.0):
                deadline = time.monotonic() + timeout_sec
                while time.monotonic() < deadline:
                    if adapter.motion_complete():
                        return
                    time.sleep(0.03)
                raise RuntimeError("원상복구 모션 완료 시간 초과")

            def move(self, poses, velocity, acceleration=None):
                adapter.begin_motion(poses, velocity, acceleration)
                self._wait_done()

            def move_joint(self, joints, velocity=None, acceleration=None):
                adapter.move_joint(joints, velocity, acceleration)
                self._wait_done()

        runner = _RecoveryRunner()
        pose = self.current_pose()
        self.validate(pose)
        if pose[2] < self.settings["travel_z_mm"] - 0.2:
            lifted = list(pose)
            lifted[2] = self.settings["travel_z_mm"]
            runner.move([lifted], self.settings.get("pick_velocity", 25.0))

        pens = PenController(self, runner)
        if self.held_stick_pose is not None:
            pens.return_to_slot(
                self.held_stick_pose,
                on_released=lambda: setattr(self, "held_stick_pose", None),
            )
        pens.return_current()

        j_vel = self.settings.get("joint_velocity", 60.0)
        j_acc = self.settings.get("joint_acceleration", 60.0)
        home_joints = self.settings.get("home_joints", [0.0, 0.0, 90.0, 0.0, 90.0, 0.0])
        runner.move_joint(home_joints, j_vel, j_acc)
        pens.gripper.off(runner)
