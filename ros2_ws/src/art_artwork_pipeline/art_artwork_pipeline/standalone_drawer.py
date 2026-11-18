"""제공된 드로잉 프로세스와 UI를 연결합니다. JobManager·SQLite를 사용하지 않습니다."""

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import threading
import time
import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from art_interfaces.msg import JobStatus
from art_interfaces.srv import CreateJob, ControlJob
from .plan import load_plan
from .pipeline_runner import job_root, atomic_json
from .live_control import EVENT_PREFIX, length, load_settings
from .recovery_store import CheckpointStore

DEFAULT_STANDALONE_SCRIPT = str(
    Path(__file__).resolve().with_name("draw_image_standalone.py")
)
DEFAULT_WS_DSR_SETUP = str(Path.home() / "ws_cobot_pjt/ws_dsr/install/setup.bash")
STATES = {
    "DISPATCHING",
    "DRAWING",
    "PAUSING",
    "PAUSED",
    "RESUMING",
    "RESETTING",
    "FORCE_STOPPED",
    "COMPLETED",
    "STOPPED",
    "RECOVERY_REQUIRED",
}


def plan_to_standalone_strokes(plan_path, out_path):
    """이전 도구 호환 출력에도 종이 mm·펜·레이어를 보존합니다."""
    plan = json.loads(Path(plan_path).read_text())
    strokes = plan["strokes"]
    if not strokes:
        raise ValueError("유효한 획이 없습니다.")
    Path(out_path).write_text(
        json.dumps(
            {
                **plan,
                "strokes_px": [s["points_mm"] for s in strokes],
                "total_length_mm": sum(length(s["points_mm"]) for s in strokes),
            },
            ensure_ascii=False,
        )
    )
    return len(strokes)


class StandaloneDrawerNode(Node):
    def __init__(self):
        super().__init__("standalone_drawer_node")
        self.declare_parameter(
            "script_path",
            os.environ.get("ART_STANDALONE_SCRIPT", DEFAULT_STANDALONE_SCRIPT),
        )
        self.declare_parameter(
            "ws_dsr_setup", os.environ.get("ART_WS_DSR_SETUP", DEFAULT_WS_DSR_SETUP)
        )
        for name in ("virtual", "dry_run", "skip_cal"):
            self.declare_parameter(
                name,
                os.environ.get("ART_STANDALONE_" + name.upper(), "").lower()
                in ("1", "true", "yes", "on"),
            )
        self._lock = threading.RLock()
        self._proc = None
        self._worker = None
        self._status = None
        self._busy = False
        self._closed = False
        self._failed = False
        self._last_event = 0.0
        self._seq = 0
        self._sha = ""
        self._receipts = {}
        self._checkpoint_error=""
        self._checkpoint_store=CheckpointStore()
        self._resume_checkpoint_id=""
        self._cleanup_checkpoint=False
        group = ReentrantCallbackGroup()
        self._pub = self.create_publisher(JobStatus, "/art/job_status", 10)
        self._create_srv = self.create_service(
            CreateJob, "/art/create_job", self._on_create_job, callback_group=group
        )
        self._control_srv = self.create_service(
            ControlJob, "/art/control_job", self._on_control_job, callback_group=group
        )
        self._timer = self.create_timer(0.25, self._tick, callback_group=group)
        self._stop_client = None
        try:
            from dsr_msgs2.srv import MoveStop

            self._stop_type = MoveStop
            self._stop_client = self.create_client(
                MoveStop,
                "/dsr01/dsr_controller2/motion/move_stop",
                callback_group=group,
            )
        except ImportError:
            self.get_logger().warning(
                "dsr_msgs2 미설치: 두산 워크스페이스 환경을 source하세요."
            )

        try:
            self._load_pending_checkpoint()
        except Exception as exc:
            self._checkpoint_error=str(exc)
            self.get_logger().error('중단점 로딩 실패: '+str(exc))

    def _load_pending_checkpoint(self):
        checkpoint=self._checkpoint_store.latest()
        if checkpoint is None:return
        summary=load_plan(checkpoint['job_id'],checkpoint['plan_path'],plan_root=job_root())
        if summary.sha256!=checkpoint['plan_sha256']:raise ValueError('중단점의 계획 SHA-256이 변경됐습니다.')
        plan=json.loads(Path(summary.path).read_text());data=checkpoint['payload']
        self._status=dict(job_id=checkpoint['job_id'],state='RECOVERY_REQUIRED',
            completed_strokes=int(data.get('completed_strokes',0)),total_strokes=summary.stroke_count,
            current_pen=(data.get('waypoint') or {}).get('pen_id',''),error_code='RECOVERY_CHECKPOINT',
            message='영속 중단점이 있습니다. 펜·종이·장비를 준비하고 재개를 누르면 정상 웨이포인트부터 이어 그립니다.',
            completed_length_mm=float(data.get('completed_length_mm',0.)),
            total_length_mm=sum(length(r['points_mm']) for r in plan['strokes']),external_force=True,
            run_id=1,control_request_id='',control_error='')
        self._sha=summary.sha256

    def _resume_saved_checkpoint(self, request, response):
        with self._lock:
            if self._busy or self._closed or (self._proc and self._proc.poll() is None) or (self._worker and self._worker.is_alive()):
                response.error_code='EXECUTION_STILL_ACTIVE';return response
            self._busy=True
        try:
            checkpoint=self._checkpoint_store.latest(job_id=request.job_id)
            if not checkpoint or not checkpoint['payload'].get('resumable'):
                raise ValueError('해당 작업에 복구 가능한 웨이포인트가 없습니다.')
            summary=load_plan(request.job_id,checkpoint['plan_path'],plan_root=job_root())
            if summary.sha256!=checkpoint['plan_sha256']:raise ValueError('중단점의 계획 SHA-256이 다릅니다.')
            load_settings()
            from .execution_recovery import assert_no_other_workers
            assert_no_other_workers(Path(self.get_parameter('script_path').value).name)
            self._observe_idle()
            with self._lock:
                self._resume_checkpoint_id=checkpoint['checkpoint_id'];self._cleanup_checkpoint=False
                self._failed=False;self._seq=0;self._last_event=time.monotonic()
                self._status['state']='DISPATCHING';self._status['control_request_id']=request.request_id
                self._status['control_error']=''
            self._worker=threading.Thread(target=self._run_standalone,args=(request.job_id,Path(summary.path)),daemon=True)
            self._worker.start()
            response.accepted=True;response.state='RESUMING';response.message='저장된 정상 웨이포인트로 복귀를 준비합니다.'
        except Exception as exc:
            response.state='RECOVERY_REQUIRED';response.error_code='RESUME_REFUSED';response.message=str(exc)[:400]
        finally:
            with self._lock:self._busy=False
        return response

    def _observe_idle(self):
        from dsr_msgs2.srv import GetRobotState, CheckMotion, GetCurrentPosx, GetCurrentVelx
        from .execution_recovery import verify_stationary
        group = ReentrantCallbackGroup()
        clients = []
        deadline = time.monotonic() + 10.0
        def call(kind, suffix, request):
            client = self.create_client(kind, '/dsr01/dsr_controller2/'+suffix, callback_group=group)
            clients.append(client)
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not client.wait_for_service(timeout_sec=min(1., remaining)):
                raise RuntimeError('정지 확인 서비스가 없습니다: '+suffix)
            future = client.call_async(request)
            done = threading.Event()
            future.add_done_callback(lambda _: done.set())
            if not done.wait(max(0., min(2., deadline-time.monotonic()))):
                raise RuntimeError('정지 확인 응답이 지연됩니다: '+suffix)
            response = future.result()
            if response is None or not response.success:
                raise RuntimeError('정지 관측에 실패했습니다: '+suffix)
            return response
        def read():
            state=call(GetRobotState,'system/get_robot_state',GetRobotState.Request()).robot_state
            motion=call(CheckMotion,'motion/check_motion',CheckMotion.Request()).status
            pos=call(GetCurrentPosx,'aux_control/get_current_posx',GetCurrentPosx.Request(ref=0))
            velocity=call(GetCurrentVelx,'aux_control/get_current_velx',GetCurrentVelx.Request(ref=0)).vel
            if not pos.task_pos_info:
                raise RuntimeError('TCP 위치 응답이 없습니다.')
            return dict(state=state,motion=motion,pose=list(pos.task_pos_info[0].data[:6]),velocity=list(velocity))
        try:
            verify_stationary(read)
        finally:
            for client in clients:
                self.destroy_client(client)

    def _reconcile_session(self, request, response):
        from .execution_recovery import assert_no_other_workers
        replacing=request.command.strip().upper()=='REPLACE'
        with self._lock:
            if self._busy or self._closed:
                response.error_code='EXECUTION_STILL_ACTIVE';return response
            alive=self._proc and self._proc.poll() is None
            if self._worker and self._worker.is_alive() and not alive:
                response.error_code='EXECUTION_STILL_ACTIVE';response.message='기존 실행기 종료를 기다리고 있습니다.';return response
            if alive and not replacing:
                response.error_code='EXECUTION_STILL_ACTIVE';return response
            self._busy=True
        try:
            if self._checkpoint_error:raise RuntimeError('중단점 저장소를 확인하세요: '+self._checkpoint_error)
            if alive:
                # POLICY-01: 새 도안의 그리기는 기존 그림을 종료한 뒤 시작합니다.
                # TODO(팀 인계): 기존 그림 우선 재개 정책으로 바꾸려면 이 분기를 수정하세요.
                # 외력이 남아 정리가 거절된 뒤 같은 새 도안으로 재시도할 수 있습니다.
                # 외부 요청은 같아도 내부 준비 확인은 시도별 ID로 구분합니다.
                attempt_id=request.request_id[:40]+'_'+str(time.monotonic_ns())[-16:]
                self._send('CANCEL',attempt_id)
                deadline=time.monotonic()+25.
                while self._proc.poll() is None and time.monotonic()<deadline:time.sleep(.05)
                if self._proc.poll() is None:raise RuntimeError('기존 그림 정리가 진행 중입니다. 실제 상태를 확인하세요.')
                if self._worker:self._worker.join(1.)
                if not self._status or self._status['state'] not in ('STOPPED','COMPLETED'):
                    raise RuntimeError('기존 그림의 정지·펜 정리가 미확정입니다.')
            checkpoint=self._checkpoint_store.latest(job_id=request.job_id)
            if checkpoint and checkpoint['payload']['runtime'].get('held_item') and not alive:
                # 노드 재시작 후에도 펜을 쥔 채 초기 개폐 명령을 보내지 않습니다.
                if not replacing:raise RuntimeError('중단점의 펜 정리를 먼저 확인해야 합니다.')
                summary=load_plan(request.job_id,checkpoint['plan_path'],plan_root=job_root())
                if summary.sha256!=checkpoint['plan_sha256']:raise ValueError('중단점의 계획 SHA-256이 다릅니다.')
                assert_no_other_workers(Path(self.get_parameter('script_path').value).name)
                self._observe_idle()
                self._resume_checkpoint_id=checkpoint['checkpoint_id'];self._cleanup_checkpoint=True
                self._failed=False;self._seq=0;self._last_event=time.monotonic()
                if self._status:self._status['state']='DISPATCHING'
                self._worker=threading.Thread(target=self._run_standalone,args=(request.job_id,Path(summary.path)),daemon=True)
                self._worker.start()
                deadline=time.monotonic()+25.
                while (not self._proc or self._proc.poll() is None) and time.monotonic()<deadline:time.sleep(.05)
                if not self._proc or self._proc.poll() is None:raise RuntimeError('이전 펜 정리가 진행 중입니다.')
                self._worker.join(1.)
                if self._status['state']!='STOPPED':raise RuntimeError('이전 펜 정리를 확인할 수 없습니다.')
            path=job_root()/request.job_id/'drawing_plan.json'
            summary=load_plan(request.job_id,str(path),plan_root=job_root())
            assert_no_other_workers(Path(self.get_parameter('script_path').value).name)
            self._observe_idle()
            assert_no_other_workers(Path(self.get_parameter('script_path').value).name)
            plan=json.loads(Path(summary.path).read_text())
            if replacing:self._checkpoint_store.mark(request.job_id,'abandoned')
            with self._lock:
                self._status=dict(job_id=request.job_id,state='STOPPED',completed_strokes=0,
                    total_strokes=summary.stroke_count,current_pen='',error_code='SESSION_RECONCILED',
                    message='기존 실행 종료와 실제 정지를 확인했습니다. 새 도안을 실행할 수 있습니다.',
                    completed_length_mm=0.,total_length_mm=sum(length(s['points_mm']) for s in plan['strokes']),
                    external_force=False,run_id=1,control_request_id=request.request_id,control_error='')
                self._sha=summary.sha256;self._failed=False;self._receipts={}
                self._resume_checkpoint_id='';self._cleanup_checkpoint=False
            self._publish_status()
            response.accepted=True;response.state='STOPPED';response.message=self._status['message']
        except Exception as exc:
            response.state='RECOVERY_REQUIRED';response.error_code='RECONCILE_REFUSED';response.message=str(exc)[:400]
        finally:
            with self._lock:self._busy=False
        return response

    def _publish_status(self):
        with self._lock:
            status = dict(self._status) if self._status else None
        if status and rclpy.ok():
            self._pub.publish(JobStatus(**status))

    def _rescue_stop(self):
        # 프로세스 종료나 통신 실패를 실제 정지 성공으로 표시하지 않습니다.
        if self._stop_client and self._stop_client.service_is_ready():
            self._stop_client.call_async(self._stop_type.Request(stop_mode=2))

    def _uncertain(self, message):
        with self._lock:
            self._failed = True
            if self._status:
                self._status.update(
                    state="RECOVERY_REQUIRED",
                    error_code="UNCONFIRMED_ROBOT_STATE",
                    message=message,
                )
        try:
            self._send("SHUTDOWN", "UNCONFIRMED")
        except Exception:
            pass
        self._rescue_stop()
        self._publish_status()

    def _tick(self):
        with self._lock:
            status = self._status
            if status and status["state"] not in (
                "COMPLETED",
                "STOPPED",
                "RECOVERY_REQUIRED",
            ):
                limit = 20.0 if status["state"] == "DISPATCHING" else 3.0
                if time.monotonic() - self._last_event > limit:
                    self._uncertain(
                        "로봇 실행기의 관측 응답이 끊겼습니다. 실제 상태를 확인하세요."
                    )
        self._publish_status()

    def _send(self, command, request_id):
        proc = self._proc
        if not proc or proc.poll() is not None or not proc.stdin:
            raise RuntimeError("로봇 실행 프로세스가 연결되지 않았습니다.")
        proc.stdin.write(
            json.dumps(
                dict(
                    job_id=self._status["job_id"],
                    command=command,
                    request_id=request_id,
                )
            )
            + "\n"
        )
        proc.stdin.flush()

    def _on_create_job(self, request, response):
        response.job_id = request.job_id
        with self._lock:
            if self._busy or self._closed:
                response.error_code = "BUSY"
                return response
            self._busy = True
        try:
            if self._checkpoint_error:raise RuntimeError('중단점 저장소를 확인하세요: '+self._checkpoint_error)
            summary = load_plan(request.job_id, request.plan_path, plan_root=job_root())
            with self._lock:
                if self._status:
                    if self._status["job_id"] == request.job_id:
                        response.accepted = self._sha == summary.sha256
                        response.state = self._status["state"]
                        response.error_code = (
                            "" if response.accepted else "PLAN_CHANGED"
                        )
                        return response
                    if self._status["state"] not in ("COMPLETED", "STOPPED"):
                        response.error_code = "JOB_ALREADY_ACTIVE"
                        response.state = self._status["state"]
                        return response
            if self._checkpoint_store.latest() is not None:
                # HTTP 외 직접 ROS 등록도 중단점의 펜 정리를 건너뛰지 못합니다.
                response.state='RECOVERY_REQUIRED';response.error_code='PENDING_CHECKPOINT'
                response.message='기존 그림을 재개하거나 REPLACE로 정리한 뒤 새 계획을 등록하세요.'
                return response
            if self._proc and self._proc.poll() is None:
                self._send("SHUTDOWN", "REPLACE")
                self._proc.wait(timeout=4.0)
                if self._worker:
                    self._worker.join(1.0)
            from .execution_recovery import assert_no_other_workers
            assert_no_other_workers(Path(self.get_parameter('script_path').value).name)
            if not self.get_parameter("dry_run").value:
                load_settings()
            script = Path(self.get_parameter("script_path").value)
            if not script.is_file():
                raise FileNotFoundError(str(script))
            raw = Path(summary.path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != summary.sha256:
                raise ValueError("실행 계획이 검증 후 변경되었습니다.")
            plan = json.loads(raw)
            if script.resolve() == Path(DEFAULT_STANDALONE_SCRIPT).resolve():
                from .draw_image_standalone import (
                    STICK_FILE,
                    PENS_FILE,
                    CALIBRATION_FILE,
                    _load_json,
                    prepare_ui_plan,
                )

                prepare_ui_plan(
                    plan,
                    _load_json(CALIBRATION_FILE, "9점 보정"),
                    _load_json(PENS_FILE, "펜 위치"),
                    _load_json(STICK_FILE, "기준 막대"),
                )

            total = sum(length(s["points_mm"]) for s in plan["strokes"])
            if not math.isfinite(total) or total <= 0:
                raise ValueError("그릴 선 길이가 0입니다.")
            with self._lock:
                self._status = dict(
                    job_id=request.job_id,
                    state="DISPATCHING",
                    completed_strokes=0,
                    total_strokes=summary.stroke_count,
                    current_pen="",
                    error_code="",
                    message="로봇 실행기를 준비합니다.",
                    completed_length_mm=0.0,
                    total_length_mm=total,
                    external_force=False,
                    run_id=1,
                    control_request_id="",
                    control_error="",
                )
                self._sha = summary.sha256
                self._seq = 0
                self._failed = False
                self._last_event = time.monotonic()
                self._receipts = {}
                self._resume_checkpoint_id="";self._cleanup_checkpoint=False
            self._worker = threading.Thread(
                target=self._run_standalone,
                args=(request.job_id, Path(summary.path)),
                daemon=True,
            )
            self._worker.start()
            response.accepted = True
            response.state = "DISPATCHING"
            response.message = "로봇의 실제 상태 확인 후 실행합니다."
        except Exception as exc:
            response.state = "STOPPED"
            response.error_code = "INVALID_PLAN_OR_SETUP"
            response.message = str(exc)[:400]
        finally:
            with self._lock:
                self._busy = False
        return response

    def _on_control_job(self, request, response):
        response.job_id = request.job_id
        command = request.command.strip().upper()
        if command=="RESET":command="STOP"
        key = request.request_id
        if command in ("RECONCILE","REPLACE"):
            return self._reconcile_session(request, response)
        if command=='RESUME' and self._status and self._status['job_id']==request.job_id and (not self._proc or self._proc.poll() is not None):
            return self._resume_saved_checkpoint(request,response)
        with self._lock:
            if not self._status or self._status["job_id"] != request.job_id:
                response.error_code = "JOB_NOT_FOUND"
                response.state = "STOPPED"
                return response
            if key in self._receipts:
                old, result = self._receipts[key]
                if old != command:
                    response.error_code = "REQUEST_ID_CONFLICT"
                    response.state = self._status["state"]
                    return response
                response.accepted, response.state, response.error_code = result
                return response
            allowed = {
                "PAUSE": ("DRAWING",),
                "RESUME": ("PAUSED", "FORCE_STOPPED", "RECOVERY_REQUIRED"),
                "STOP": ("DRAWING","PAUSING","PAUSED","RESUMING","FORCE_STOPPED"),
                "CANCEL": ("DISPATCHING","DRAWING","PAUSED","FORCE_STOPPED","COMPLETED"),
            }
            if (
                not key
                or len(key) > 64
                or len(self._receipts) >= 10000
                or self._status["state"] not in allowed.get(command, ())
            ):
                response.state = self._status["state"]
                response.error_code = "INVALID_TRANSITION"
                return response
            target = {
                "PAUSE": "PAUSING",
                "RESUME": "RESUMING",
                "STOP": "STOPPING",
                "CANCEL": "STOPPING",
            }[command]
            try:
                self._send(command, key)
            except Exception as exc:
                response.error_code = "PROCESS_UNAVAILABLE"
                response.state = "RECOVERY_REQUIRED"
                self._uncertain(str(exc))
                return response
            self._receipts[key] = (command, (True, target, ""))
            self._status["state"] = target
        response.accepted = True
        response.state = target
        response.message = "요청 수락은 실제 홈 도달·재개 확인을 뜻하지 않습니다."
        return response

    def _build_command(self, path):
        cmd = [
            "python3",
            "-u",
            str(self.get_parameter("script_path").value),
            "--input",
            str(path),
            "--ui-control",
            "--job-id",
            path.parent.name,
            "--plan-sha256",
            self._sha,
        ]
        if self._resume_checkpoint_id:
            cmd.extend(['--resume-checkpoint',self._resume_checkpoint_id])
            if self._cleanup_checkpoint:cmd.append('--cleanup-checkpoint')
        for flag in ("virtual", "dry_run", "skip_cal"):
            if self.get_parameter(flag).value:
                cmd.append("--" + flag.replace("_", "-"))
        setup = str(self.get_parameter("ws_dsr_setup").value)
        if (
            importlib.util.find_spec("DSR_ROBOT2") is None
            and setup
            and Path(setup).is_file()
        ):
            return [
                "bash",
                "-c",
                "source "
                + shlex.quote(setup)
                + " && exec "
                + " ".join(shlex.quote(v) for v in cmd),
            ]
        return cmd

    def _event(self, event):
        with self._lock:
            if self._failed:
                return
            if (
                not self._status
                or event.get("job_id") != self._status["job_id"]
                or event.get("protocol") != 1
            ):
                raise ValueError("다른 작업의 로봇 이벤트입니다.")
            if event.get("event") == "CONTROL_REJECTED":
                key = event.get("request_id", "")
                self._status.update(
                    control_request_id=key,
                    control_error=event.get("error", "CONTROL_REJECTED"),
                )
                if key in self._receipts:
                    self._receipts[key] = (
                        self._receipts[key][0],
                        (False, self._status["state"], "INVALID_TRANSITION"),
                    )
                return
            if type(event.get("seq")) is not int or event["seq"] <= self._seq:
                return
            if event.get("state") not in STATES:
                raise ValueError("알 수 없는 로봇 상태입니다.")
            total = event.get("total_length_mm")
            done = event.get("completed_length_mm")
            if (
                type(total) not in (int, float)
                or type(done) not in (int, float)
                or not math.isfinite(done)
                or not math.isfinite(total)
                or not 0 <= done <= total + 1e-6
                or not math.isclose(
                    total, self._status["total_length_mm"], rel_tol=1e-8, abs_tol=1e-6
                )
            ):
                raise ValueError("로봇 선 길이가 승인한 계획과 다릅니다.")
            if (
                event.get("total_strokes") != self._status["total_strokes"]
                or type(event.get("completed_strokes")) is not int
                or not 0 <= event["completed_strokes"] <= event["total_strokes"]
            ):
                raise ValueError("로봇 획 수 관측이 잘못됐습니다.")
            if (
                type(event.get("run_id")) is not int
                or event["run_id"] < self._status["run_id"]
            ):
                return
            if type(event.get("external_force")) is not bool or not all(
                isinstance(event.get(k), str)
                for k in (
                    "current_pen",
                    "error_code",
                    "message",
                    "control_request_id",
                    "control_error",
                )
            ):
                raise ValueError("로봇 이벤트의 타입이 잘못됐습니다.")
            if event["state"] == "COMPLETED" and (
                event["completed_strokes"] != event["total_strokes"]
                or not math.isclose(done, total, abs_tol=1e-6)
            ):
                raise ValueError("모든 선의 완료가 확인되지 않았습니다.")
            self._seq = event["seq"]
            self._last_event = time.monotonic()
            for name in self._status:
                if name != "job_id":
                    self._status[name] = event[name]
            if self.get_parameter("virtual").value:
                self._status["message"] = "[가상 모드] " + self._status["message"]
        self._publish_status()

    def _run_standalone(self, job_id, path):
        try:
            proc = subprocess.Popen(
                self._build_command(path),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with self._lock:
                self._proc = proc
            tail = []
            for line in proc.stdout:
                if line.startswith(EVENT_PREFIX):
                    try:
                        self._event(json.loads(line[len(EVENT_PREFIX) :]))
                    except (ValueError, KeyError, TypeError) as exc:
                        self._uncertain("로봇 이벤트 오류: " + str(exc))
                elif line.strip():
                    tail = (tail + [line.strip()])[-5:]
            code = proc.wait()
            with self._lock:
                expected = self._status["state"] in (
                    "STOPPED",
                    "COMPLETED",
                    "RECOVERY_REQUIRED",
                )
            if self.get_parameter("dry_run").value and code == 0:
                with self._lock:
                    self._status.update(
                        state="STOPPED",
                        error_code="DRY_RUN_ONLY",
                        message="로봇 이동 없이 미리보기만 생성했습니다.",
                    )
            elif code != 0 or not expected:
                self._uncertain(
                    "로봇 실행 종료가 미확정입니다: "
                    + (tail[-1] if tail else str(code))
                )
        except Exception as exc:
            self._uncertain(str(exc))
        finally:
            self._publish_status()

    def stop_worker(self):
        self._closed = True
        if self._proc and self._proc.poll() is None:
            try:
                self._send("SHUTDOWN", "EXIT")
                self._proc.wait(timeout=4.0)
            except Exception:
                self._rescue_stop()
        if self._worker:
            self._worker.join(1.0)

    def destroy_node(self):
        self.stop_worker()
        return super().destroy_node()


def main(args=None):
    from rclpy.signals import SignalHandlerOptions

    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = StandaloneDrawerNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    worker = threading.Thread(target=executor.spin, daemon=True)
    worker.start()
    try:
        while rclpy.ok():
            worker.join(0.2)
    except KeyboardInterrupt:
        node.get_logger().info("종료 요청: 로봇 실행기의 정지 응답을 기다립니다.")
    finally:
        node.stop_worker()
        executor.shutdown(timeout_sec=5)
        worker.join(5)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
