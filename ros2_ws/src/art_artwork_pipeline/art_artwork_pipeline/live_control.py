"""제공된 드로잉 코드의 모션을 제어하는 메모리 세션과 JSON 통신 규약."""

import json
import math
import os
from pathlib import Path
import threading
import time

EVENT_PREFIX = "A4_EVENT "


class ResumeDrawing(Exception):
    """저장한 계획의 중단점으로 동일 그림의 실행을 복원합니다."""
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint


class ForceStopped(Exception):
    """외력·보호 정지입니다. 자동 홈 이동을 금지합니다."""


class WorkerExit(Exception):
    """프로세스 종료 요청입니다."""


class CancelDrawing(Exception):
    """이전 CANCEL API의 중단 요청입니다."""


def load_settings(path=None):
    path = Path(
        path
        or os.environ.get(
            "ART_MOTION_CONTROL_CONFIG",
            str(Path.home() / ".ros/a4_motion_control.json"),
        )
    ).expanduser()
    data = json.loads(path.read_text())
    if data.get("validated") is not True:
        raise ValueError(
            "홈 왕복 경로와 선택한 보호 방식을 확인한 설정이 필요합니다."
        )
    mode = data.setdefault("protection_mode", "software_force")
    if mode not in ("software_force", "controller"):
        raise ValueError("지원하지 않는 보호 모드입니다.")
    if mode == "controller":
        if data.get("controller_collision_verified") is not True or data.get("home_path_verified") is not True:
            raise ValueError("제어기 충돌 감지·보호 정지와 홈 왕복 경로를 확인해야 합니다.")
    else:
        for key in ("force_limits", "force_bias"):
            values = data.get(key)
            if (
                not isinstance(values, list)
                or len(values) != 6
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
            ):
                raise ValueError(key + "의 실측값 6개가 필요합니다.")
        if any(v <= 0 for v in data["force_limits"]):
            raise ValueError("외력 한계는 양수여야 합니다.")
    for key, default, upper in [
        ("motion_timeout", 120.0, 600.0),
        ("position_tolerance", 0.5, 1.0),
        ("joint_tolerance", 0.2, 1.0),
        ("recovery_lift_mm", 15.0, 30.0),
        ("recovery_orientation_tolerance_deg", 1.0, 2.0),
    ]:
        value = data.setdefault(key, default)
        if (
            type(value) not in (float, int)
            or not math.isfinite(value)
            or not 0 < value <= upper
        ):
            raise ValueError("잘못된 설정: " + key)
    return data


def length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def fraction_at(point, start, end, tolerance):
    delta = [b - a for a, b in zip(start[:3], end[:3])]
    square = sum(v * v for v in delta)
    fraction = (
        max(
            0.0,
            min(
                1.0,
                sum((p - a) * d for p, a, d in zip(point[:3], start[:3], delta))
                / square,
            ),
        )
        if square
        else 1.0
    )
    projected = [a + fraction * d for a, d in zip(start[:3], delta)]
    if math.dist(point[:3], projected) > tolerance:
        raise RuntimeError(
            "실제 정지 위치가 현재 선분에서 벗어났습니다. 자동 재개하지 않습니다."
        )
    return fraction


class LiveControl:
    def __init__(self, job_id, total, total_strokes, settings, emit=None):
        self.job_id = job_id
        self.total = total
        self.total_strokes = total_strokes
        self.settings = settings
        self.send = emit or (
            lambda event: print(
                EVENT_PREFIX + json.dumps(event, ensure_ascii=False, allow_nan=False),
                flush=True,
            )
        )
        self.lock = threading.RLock()
        self.intent = None
        self.closed = False
        self.receipts = {}
        self.state = "DISPATCHING"
        self.done = 0.0
        self.completed = 0
        self.pen = ""
        self.run_id = 1
        self.seq = 0
        self.force_latched = False
        self.sensing = False
        self.handling_reset = False
        self.request_id = ""
        self.command = ""
        self.command_run = 0
        self.control_error = ""
        self.api = None
        self.journal = None
        self.current_checkpoint = None
        self.waypoint = None
        self.last_force = [0.0]*6
        self.runtime = {}
        self.emit(message="로봇 설정과 기존 기준면 측정을 준비합니다.")

    def bind(self, api, home, safe_z):
        self.api = api
        self.home = list(home)
        self.safe_z = safe_z

    def emit(self, state=None, message="", error=""):
        with self.lock:
            if state:
                self.state = state
            self.seq += 1
            self.send(
                dict(
                    protocol=1,
                    seq=self.seq,
                    job_id=self.job_id,
                    state=self.state,
                    completed_strokes=self.completed,
                    total_strokes=self.total_strokes,
                    completed_length_mm=min(self.total, max(0.0, self.done)),
                    total_length_mm=self.total,
                    current_pen=self.pen,
                    error_code=error,
                    message=message,
                    external_force=self.force_latched,
                    run_id=self.run_id,
                    control_request_id=self.request_id,
                    control_error=self.control_error,
                )
            )

    def request(self, command, request_id):
        # 이전 RESET 클라이언트도 이제 처음부터 그리지 않고 정지점 보존으로 처리합니다.
        if command == "RESET": command = "STOP"
        with self.lock:
            if command == "SHUTDOWN":
                self.closed = True
                return
            if request_id in self.receipts:
                if self.receipts[request_id] != command:
                    self.control_error = "REQUEST_ID_CONFLICT"
                self.emit()
                return
            allowed = {
                "PAUSE": ("DRAWING",),
                "RESUME": ("PAUSED", "FORCE_STOPPED"),
                "STOP": ("DRAWING", "PAUSING", "PAUSED", "RESUMING", "FORCE_STOPPED"),
                "CANCEL": ("DISPATCHING", "DRAWING", "PAUSING", "PAUSED", "RESUMING", "FORCE_STOPPED", "COMPLETED"),
            }
            if (
                not request_id
                or len(request_id) > 64
                or len(self.receipts) >= 10000
                or self.state not in allowed.get(command, ())
                or self.intent
                and not (command in ("STOP","CANCEL") and self.intent in ("PAUSE", "RESUME"))
            ):
                self.request_id = request_id
                self.control_error = "INVALID_TRANSITION"
                self.emit(message="현재 상태에서는 해당 제어를 실행하지 않습니다.")
                return
            self.receipts[request_id] = command
            self.intent = command
            self.request_id = request_id
            self.command = command
            self.command_run = self.run_id
            self.control_error = ""
            self.emit(
                {
                    "PAUSE": "PAUSING",
                    "RESUME": "RESUMING",
                    "STOP": "STOPPING",
                    "CANCEL": "STOPPING",
                }[command],
                "명령을 수신했습니다. 실제 동작 확인 중입니다.",
            )

    def read_commands(self, stream):
        try:
            for line in stream:
                try:
                    value = json.loads(line)
                    if (
                        isinstance(value, dict)
                        and value.get("job_id") == self.job_id
                        and isinstance(value.get("command"), str)
                        and isinstance(value.get("request_id"), str)
                    ):
                        self.request(value["command"], value["request_id"])
                except (ValueError, AttributeError, TypeError):
                    continue
        except (OSError, ValueError):
            pass
        finally:
            self.closed = True

    def check(self, controls=True, ignore_alarm=False):
        if self.closed:
            raise WorkerExit()
        if not ignore_alarm:
            reason = getattr(self.api, "alarm_snapshot", lambda: (0, ""))()[1]
            if reason:
                raise ForceStopped(reason)
        state = self.api.state()
        if state in (3, 5, 6, 9, 10):
            raise ForceStopped("제어기 보호 정지 상태 " + str(state))
        if state not in (1, 2):
            raise RuntimeError("이동 가능한 로봇 상태가 아닙니다: " + str(state))
        if self.sensing:
            force = self.api.force()
            if len(force) != 6 or not all(math.isfinite(v) for v in force):
                raise RuntimeError("유효한 외력 관측이 없습니다.")
            self.last_force = list(force)
            if self.settings.get("protection_mode", "software_force") == "software_force" and any(
                abs(v-b)>limit for v,b,limit in zip(force,self.settings["force_bias"],self.settings["force_limits"])
            ):
                raise ForceStopped("설정된 외력 기준을 초과했습니다.")
        if controls and self.intent == "CANCEL":
            raise CancelDrawing()

    def motion(
        self, target, joint=False, vel=25.0, acc=25.0, drawing=None, allow_pause=True
    ):
        target = [float(v) for v in target]
        if len(target) != 6 or not all(math.isfinite(v) for v in target):
            raise ValueError("유효한 목표 자세가 필요합니다.")
        self.check()
        if drawing:self.sample_drawing(drawing,target)
        self.api.begin(target, joint, vel, acc)
        elapsed = 0.0
        previous = time.monotonic()
        while True:
            self.check()
            now = time.monotonic()
            elapsed += now - previous
            previous = now
            if allow_pause and self.intent in ("PAUSE", "STOP"):
                command = self.intent
                self.api.stop()
                stopped = self.api.pose()
                self.record_interruption(command, stopped, stop_confirmed=True)
                if drawing:
                    self.done = drawing[2] + drawing[3] * fraction_at(
                        stopped,
                        drawing[0],
                        drawing[1],
                        self.settings["position_tolerance"],
                    )
                if command == "PAUSE":
                    lifted = list(stopped)
                    lifted[2] = self.safe_z(stopped)
                    self.motion(lifted, vel=25.0, acc=25.0, allow_pause=False)
                    return_joints = self.api.joints()
                    self.motion(
                        self.home, joint=True, vel=30.0, acc=30.0, allow_pause=False
                    )
                if command == "PAUSE" and self.current_checkpoint:
                    # 홈 도달 후에만 저장하므로 중간 종료를 홈 도달로 오인하지 않습니다.
                    self.runtime['pause_home']=dict(home=list(self.home),return_joints=list(return_joints),lifted=list(lifted))
                    self.journal.store.update_runtime(self.current_checkpoint['checkpoint_id'],self.runtime)
                    self.current_checkpoint=self.journal.store.latest(checkpoint_id=self.current_checkpoint['checkpoint_id'])
                with self.lock:
                    self.intent = None
                self.emit(
                    "PAUSED",
                    "정지점 저장 완료. 펜·종이를 확인한 뒤 재개하면 마지막 정상 웨이포인트부터 이어 그립니다.",
                )
                while self.intent != "RESUME":
                    self.check()
                    if self.intent == "STOP":
                        # 홈에 도착한 일시정지를 정지로 바꿔도 저장한 복귀점은 유지합니다.
                        with self.lock:self.intent = None
                        self.emit("PAUSED", "중단점을 보존했습니다. 재개하거나 새 도안을 그릴 수 있습니다.")
                    self.emit()
                    time.sleep(0.05)
                self.check()
                self.confirm_recovery_ready()
                if self.current_checkpoint:
                    raise ResumeDrawing(self.current_checkpoint)
                if command == "STOP":
                    with self.lock:self.intent=None
                    self.emit("DRAWING", "저장된 중단 위치에서 남은 선을 이어 그립니다.")
                    self.api.begin(target,joint,vel,acc)
                    elapsed=0.;previous=time.monotonic()
                    continue
                if (
                    max(abs(a - b) for a, b in zip(self.api.joints(), self.home))
                    > self.settings["joint_tolerance"]
                ):
                    raise RuntimeError("일시정지 중 홈 자세가 변경됐습니다.")
                self.motion(
                    return_joints, joint=True, vel=30.0, acc=30.0, allow_pause=False
                )
                if (
                    math.dist(self.api.pose()[:3], lifted[:3])
                    > self.settings["position_tolerance"]
                ):
                    raise RuntimeError("복귀 위치가 달라졌습니다.")
                self.motion(stopped, vel=25.0, acc=25.0, allow_pause=False)
                with self.lock:
                    self.intent = None
                self.emit("DRAWING", "그리던 선분의 남은 위치부터 재개합니다.")
                self.api.begin(target, joint, vel, acc)
                elapsed = 0.0
                previous = time.monotonic()
            if drawing:
                self.sample_drawing(drawing, target)
                self.done = drawing[2] + drawing[3] * fraction_at(
                    self.api.pose(),
                    drawing[0],
                    drawing[1],
                    self.settings["position_tolerance"],
                )
            self.emit()
            if self.api.finished(target, joint):
                return
            if elapsed > self.settings["motion_timeout"]:
                raise RuntimeError("모션 완료 확인 시간 초과")
            time.sleep(0.02)

    def draw_line(self, target, vel, acc, planned_start=None, stroke_id=None, point_index=None):
        start = list(planned_start) if planned_start is not None else self.api.pose()
        segment = math.dist(start[:2], target[:2])
        base = self.done
        if stroke_id is not None:
            self.waypoint=dict(stroke_id=int(stroke_id),point_index=int(point_index),return_pose=start,
                               base_length_mm=base,pen_id=self.pen)
        self.motion(
            target, vel=vel, acc=acc, drawing=(start, list(target), base, segment)
        )
        self.done = base + segment

    def begin_run(self):
        self.sensing = True
        self.emit("DRAWING", "확정된 그림·문구 경로를 실행합니다.")

    def attach_journal(self, journal):
        self.journal=journal

    def sample_drawing(self, drawing, target):
        if not self.journal or not self.waypoint:return
        self.journal.runtime=dict(self.runtime)
        actual=self.api.pose()
        fraction_at(actual,drawing[0],drawing[1],self.settings["position_tolerance"])
        self.journal.sample(target_pose=target,actual_pose=actual,force=self.last_force,
            waypoint=self.waypoint,completed_strokes=self.completed,completed_length_mm=self.done,runtime=self.runtime)

    def record_interruption(self, cause, actual_pose=None, *, stop_confirmed=False):
        if not self.journal:return
        self.journal.runtime=dict(self.runtime)
        checkpoint_id=self.journal.interrupt(cause,actual_pose,stop_confirmed=stop_confirmed,force=self.last_force)
        self.current_checkpoint=self.journal.store.latest(checkpoint_id=checkpoint_id)

    def confirm_recovery_ready(self):
        snapshot=getattr(self.api,"alarm_snapshot",lambda:(0,""))()
        self.api.ready()
        self.check(controls=False,ignore_alarm=True)
        if hasattr(self.api,"acknowledge_alarm"):self.api.acknowledge_alarm(snapshot[0])

    def recovery_move(self, checkpoint):
        data=checkpoint['payload']
        if not data.get('resumable') or not data.get('waypoint'):
            raise RuntimeError('복구 가능한 그리기 중단점이 없습니다. 장비 상태를 확인하세요.')
        self.confirm_recovery_ready()
        target=[float(v) for v in data['target_pose']]
        paused_home=data['runtime'].get('pause_home')
        if paused_home:
            values=[*paused_home['home'],*paused_home['return_joints'],*paused_home['lifted']]
            if len(values)!=18 or not all(type(v) in (int,float) and math.isfinite(v) for v in values):
                raise RuntimeError('저장된 홈 왕복 경로가 잘못됐습니다.')
            if paused_home['home']!=list(self.home) or max(abs(a-b) for a,b in zip(self.api.joints(),self.home))>self.settings['joint_tolerance']:
                raise RuntimeError('일시정지 중 홈 자세가 변경됐습니다.')
            self.motion(paused_home['return_joints'],joint=True,vel=30.,acc=30.,allow_pause=False)
            if math.dist(self.api.pose()[:3],paused_home['lifted'][:3])>self.settings['position_tolerance']:
                raise RuntimeError('복귀 위치가 달라졌습니다.')
        current=self.api.pose()
        if max(abs(a-b) for a,b in zip(current[3:],target[3:]))>self.settings.get('recovery_orientation_tolerance_deg',1.):
            raise RuntimeError('복구 자세의 방향이 달라졌습니다. 종이와 펜 자세를 확인하세요.')
        bounds=data['runtime'].get('paper_bounds')
        if bounds and not (bounds[0]-20<=current[0]<=bounds[1]+20 and bounds[2]-20<=current[1]<=bounds[3]+20):
            raise RuntimeError('현재 위치가 검증된 종이 복구 영역 밖입니다. 자동 복귀하지 않습니다.')
        self.completed=int(data['completed_strokes']);self.done=float(data['completed_length_mm'])
        self.pen=data['waypoint']['pen_id'];self.runtime=dict(data['runtime']);self.runtime.pop('pause_home',None)
        self.waypoint=dict(data['waypoint']);self.force_latched=False
        with self.lock:self.intent=None
        self.emit('RESUMING','실측 위치는 안전 상승에만 사용하고 저장된 정상 웨이포인트로 복귀합니다.')
        height=max(current[2],target[2]+self.settings.get('recovery_lift_mm',15.))
        ceiling=data['runtime'].get('recovery_ceiling_mm')
        if ceiling is not None and height>ceiling:raise RuntimeError('복구 상승 높이가 검증된 범위를 넘습니다.')
        lifted=list(current);lifted[2]=height
        self.motion(lifted,vel=10.,acc=10.,allow_pause=False)
        above=list(target);above[2]=height
        self.motion(above,vel=10.,acc=10.,allow_pause=False)
        self.motion(target,vel=5.,acc=5.,allow_pause=False)
        if self.journal:
            self.journal.resumed()
        self.current_checkpoint=None
        self.emit('DRAWING','기록된 마지막 정상 웨이포인트부터 남은 경로를 이어 그립니다.')

    def complete(self):
        self.done=self.total
        if self.journal:self.journal.store.mark(self.job_id,'resolved')
        self.emit('COMPLETED','그리기 이동과 홈 도달을 확인했습니다.')
        while True:
            if self.closed:raise WorkerExit()
            if self.intent=='CANCEL':raise CancelDrawing()
            self.emit();time.sleep(.05)

    def wait_force_reset(self, reason):
        # 함수명은 이전 호출부 호환용입니다. 이제 RESET으로 처음부터 그리지 않습니다.
        self.force_latched=True
        try:
            self.api.stop()
        except Exception:
            try:self.record_interruption(str(reason),self.api.pose(),stop_confirmed=False)
            except Exception:pass
            raise
        self.record_interruption(str(reason),self.api.pose(),stop_confirmed=True)
        with self.lock:self.intent=None
        self.emit('FORCE_STOPPED',str(reason),'EXTERNAL_FORCE')
        while True:
            if self.closed:raise WorkerExit()
            if self.intent in ('RESUME','CANCEL'):
                command=self.intent
                try:
                    self.confirm_recovery_ready()
                    if command=='CANCEL':
                        self.force_latched=False
                        with self.lock:self.intent=None
                        raise CancelDrawing()
                    if not self.current_checkpoint:
                        raise RuntimeError('영속 중단점이 없어 자동 재개할 수 없습니다.')
                    raise ResumeDrawing(self.current_checkpoint)
                except (ForceStopped,RuntimeError) as exc:
                    with self.lock:
                        self.intent=None;self.control_error='RESUME_NOT_READY'
                    self.emit('FORCE_STOPPED','재개 준비를 확인하세요: '+str(exc),'EXTERNAL_FORCE')
            if self.intent=='STOP':
                with self.lock:self.intent=None
            self.emit();time.sleep(.05)


class DsrMotionApi:
    """SDK 호출은 모션 스레드 하나에서 직렬화합니다. stdin 스레드는 명령만 기록합니다."""

    def __init__(
        self,
        node,
        dsr,
        virtual=False,
        robot_id="dsr01",
        tool_name="Tool_Weight",
        tcp_name="GripperDA_v1",
    ):
        import rclpy
        from dsr_msgs2.srv import MoveStop

        self.node = node
        self.dsr = dsr
        self.virtual = virtual
        self.monitor = None
        self.tool_name = tool_name
        self.tcp_name = tcp_name
        self.rclpy = rclpy
        self.stop_type = MoveStop
        self.client = node.create_client(
            MoveStop, f"/{robot_id}/dsr_controller2/motion/move_stop"
        )

    def start_monitor(self, robot_id):
        from .driver_events import DriverEventMonitor
        self.monitor = DriverEventMonitor(self.node.context, robot_id)
        try:
            self.monitor.ensure_ready()
        except Exception:
            self.close()
            raise

    def alarm_snapshot(self):
        return self.monitor.latch.snapshot() if self.monitor else (0, "")

    def acknowledge_alarm(self, generation):
        if self.monitor:
            self.monitor.latch.acknowledge(generation)

    def close(self):
        if self.monitor:
            self.monitor.close()
            self.monitor = None

    def pose(self):
        return self._vector(self.dsr.get_current_posx(0)[0][:6])

    def joints(self):
        return self._vector(self.dsr.get_current_posj())

    def force(self):
        return self._vector(self.dsr.get_tool_force(0))

    def state(self):
        return self.dsr.get_robot_state()

    def _vector(self, value):
        result = [float(v) for v in value]
        if len(result) != 6 or not all(math.isfinite(v) for v in result):
            raise RuntimeError("로봇 관측값이 유효하지 않습니다.")
        return result

    def ready(self):
        deadline = time.monotonic() + 2.0
        while self.state() == 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        if self.state() != 1:
            raise RuntimeError(
                "운영자가 보호 정지를 해제하고 STANDBY를 확인해야 합니다."
            )
        if not self.virtual:
            if self.dsr.get_robot_system() != 0:
                raise RuntimeError("실물 제어기 모드가 아닙니다.")
            if (
                self.dsr.get_tool() != self.tool_name
                or self.dsr.get_tcp() != self.tcp_name
            ):
                raise RuntimeError("일시정지 중 Tool/TCP가 변경되었습니다.")

    def finished(self, target, joint):
        current = self.joints() if joint else self.pose()
        velocity = self._vector(self.dsr.get_current_velx(0))
        return (
            self.dsr.check_motion() == 0
            and max(abs(a - b) for a, b in zip(current, target)) <= 0.1
            and all(abs(v) < 0.01 for v in velocity)
        )

    def begin(self, target, joint, vel, acc):
        if self.finished(target, joint):
            return
        fn = self.dsr.amovej if joint else self.dsr.amovel
        if fn(target, vel=vel, acc=acc, mod=0) != 0:
            raise RuntimeError("두산 비동기 모션이 거절되었습니다.")

    def stop(self):
        request_ok = False
        if self.client.wait_for_service(timeout_sec=1.0):
            future = self.client.call_async(self.stop_type.Request(stop_mode=2))
            self.rclpy.spin_until_future_complete(self.node, future, timeout_sec=2.0)
            request_ok = (
                future.done()
                and future.result() is not None
                and future.result().success
            )
        # 보호 정지 상태는 정지 RPC를 거절할 수 있습니다. 상태·위치·속도로 실제 정지를 별도로 확인합니다.
        if not request_ok and self.state() not in (3, 5, 6, 9, 10) and not self.alarm_snapshot()[1]:
            raise RuntimeError("정지 요청 결과가 미확정입니다.")
        end = time.monotonic() + 3.0
        stable = 0
        previous = None
        while time.monotonic() < end:
            pose = self.pose()
            velocity = self._vector(self.dsr.get_current_velx(0))
            if (
                self.dsr.check_motion() == 0
                and all(abs(v) < 0.01 for v in velocity)
                and (previous is None or math.dist(previous[:3], pose[:3]) <= 0.1)
            ):
                stable += 1
                if stable >= 3:
                    return
            else:
                stable = 0
            previous = pose
            time.sleep(0.02)
        raise RuntimeError("실제 정지를 관측하지 못했습니다.")
