"""참고 드로잉 코드의 이동 기능만 ROS 서비스로 연결합니다. 이미지 처리·접촉 탐색은 없습니다."""

import math
import time
from .equipment_settings import validate_equipment, profile_unchanged
from .motion_safety import validate_pose
from .doosan_motion_control import DoosanMotionControl


class DoosanAdapter:
    def __init__(self, node=None, settings=None):
        self.node, self.settings = node, settings
        self.held_pen = None
        self._target = None
        self._motion_kind = "task"
        self.control = None
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

    def require_ready(self):
        if self.control is None or self.settings is None:
            raise RuntimeError("실물 프로필·M0609·RG2 준비 검증이 필요합니다.")
        if not self.equipment_ready():
            raise RuntimeError("장비 프로필·Tool·TCP·연결 상태를 확인할 수 없습니다.")

    def equipment_ready(self):
        if self.control is None:
            return False
        deadline = time.monotonic() + 2.0
        return self.control.call("system", deadline).robot_system == 0

    def preflight(self):
        self.require_ready()
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

    def read_tool_force_z(self, ref=0):
        self.require_ready()
        deadline = time.monotonic() + 2.0
        res = self.control.call("force", deadline, ref=int(ref))
        val = float(res.tool_force[2])
        if not math.isfinite(val):
            raise RuntimeError("Fz 센서 측정값이 유효하지 않습니다.")
        return val

    def begin_motion(self, poses, velocity, acceleration=None, mod=0):
        self.require_ready()
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
                opt=1,
                **fields,
            )

    def motion_complete(self):
        if self._motion_kind in ("joint", "rel"):
            deadline = time.monotonic() + 3.0
            _, vel = self.control.observed(deadline)
            status = self.control.call("motion", deadline).status
            return status == 0 and all(abs(v) <= 0.01 for v in vel)
        if self._target is None:
            return False
        deadline = time.monotonic() + 3.0
        pose, vel = self.control.observed(deadline)
        status = self.control.call("motion", deadline).status
        return (
            status == 0
            and math.dist(pose[:3], self._target[:3]) <= 0.2
            and max(abs(a - b) for a, b in zip(pose[3:], self._target[3:])) <= 0.2
            and all(abs(v) <= 0.01 for v in vel)
        )

    def at_pose(self, target):
        """같은 목표로 이동을 생략할 때도 실제 정지와 자세를 관측합니다."""
        pose = self.control.stationary(time.monotonic() + 3.0)
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
            return self.pen_up_confirmed()
        target = list(pose)
        target[2] = self.settings["travel_z_mm"]
        self.begin_motion([target], self.settings["pick_velocity"])
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self.motion_complete():
                return self.pen_up_confirmed()
            time.sleep(0.02)
        return False

    def pen_up_confirmed(self):
        pose, velocity = self.control.observed(time.monotonic() + 3.0)
        if any(abs(v) > 0.01 for v in velocity):
            return False
        io = self.settings["gripper"]
        has_inputs = io.get("grip_input") is not None and io.get("release_input") is not None
        if self.held_pen is None:
            if not has_inputs:
                return pose[2] >= self.settings["travel_z_mm"] - 0.2
            return (
                pose[2] >= self.settings["travel_z_mm"] - 0.2
                and self.read_input(io["release_input"]) == 1
                and self.read_input(io["grip_input"]) == 0
            )
        a, b, c = self.settings["plane_abc"]
        contact = (
            a * pose[0]
            + b * pose[1]
            + c
            + self.settings["pen_slots"][self.held_pen]["z_offset_mm"]
        )
        lifted = pose[2] >= contact + self.settings["stroke_lift_mm"] - 0.2
        if not has_inputs:
            return lifted
        return lifted and self.read_input(io["grip_input"]) == 1
