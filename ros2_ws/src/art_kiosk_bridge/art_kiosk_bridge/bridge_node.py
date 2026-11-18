# [파일 역할] KioskBridge ROS 2 담당
# [동작] FastAPI 쪽 HTTP 요청을 ROS Service로 전달하고 /art/job_status를 수신·캐시합니다.
# [주의] 이 파일은 로봇을 움직이지 않습니다. HTTP 202와 실제 작업 완료를 혼동하면 안 됩니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""ROS 2 Service clients and confirmed JobStatus subscriber.

Executor spins in its own thread (main.py); HTTP handler awaits nonblocking
call_async futures. This bridge never calls the robot driver directly.
"""

from __future__ import annotations

import asyncio
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.action.graph import get_action_server_names_and_types_by_node
from art_interfaces.action import PrepareArtwork
from art_interfaces.msg import JobStatus
from art_interfaces.srv import ControlJob, CreateJob

from .errors import ArtworkFailed, ContractMismatch, ServiceTimeout, ServiceUnavailable
from .schemas import JobCommandReply, JobStatusReply


# [핵심 기능] ROS 클라이언트와 상태 Topic 구독자를 만드는 브리지 노드
class KioskBridgeNode(Node):
    def __init__(
        self,
        *,
        create_service: str = "/art/create_job",
        control_service: str = "/art/control_job",
        status_topic: str = "/art/job_status",
        timeout_sec: float = 3.0,
        artwork_action: str = "/art/prepare_artwork",
    ) -> None:
        super().__init__("kiosk_bridge_node")
        self.timeout_sec = timeout_sec
        self._artwork_action = self.resolve_topic_name(artwork_action)
        self._artwork = ActionClient(self, PrepareArtwork, self._artwork_action)
        self._create_client = self.create_client(CreateJob, create_service)
        self._control_client = self.create_client(ControlJob, control_service)
        self._lock = threading.Lock()
        self._statuses: dict[str, JobStatusReply] = {}
        self._status_subscription = self.create_subscription(
            JobStatus, status_topic, self._on_status, 10
        )
        # TEAM_SYNC(JobManager): exact service/topic names, message definitions,
        # QoS and reconnect behavior must match the real JobManager.

    # [핵심 기능] JobStatus Topic을 받아 최근 상태를 HTTP 조회용 메모리에 저장
    def _on_status(self, msg: JobStatus) -> None:
        if not msg.job_id:
            self.get_logger().warning("Ignoring status without job_id")
            return
        # TEAM_SYNC(Robot/JobManager): message must represent an OBSERVED/confirmed
        # manager state. Never synthesize PAUSED from a PAUSE HTTP request.
        status = JobStatusReply(
            job_id=msg.job_id,
            state=msg.state,
            completed_strokes=int(msg.completed_strokes),
            total_strokes=int(msg.total_strokes),
            completed_length_mm=float(msg.completed_length_mm),total_length_mm=float(msg.total_length_mm),
            external_force=msg.external_force,run_id=int(msg.run_id),control_request_id=msg.control_request_id,control_error=msg.control_error,
            current_pen=msg.current_pen,
            error_code=msg.error_code,
            message=msg.message,
            observed_at_unix=time.time(),
        )
        with self._lock:
            self._statuses[msg.job_id] = status

    # [핵심 기능] JobManager의 생성·제어 Service가 사용 가능한지 확인
    def is_ready(self) -> bool:
        return (self._create_client.service_is_ready() and self._control_client.service_is_ready()
                and self._service_server_count(self._create_client.srv_name) == 1
                and self._service_server_count(self._control_client.srv_name) == 1)

    def _service_server_count(self, service_name):
        return sum(any(name == service_name for name, _ in
                       self.get_service_names_and_types_by_node(node, namespace))
                   for node, namespace in self.get_node_names_and_namespaces())

    def _artwork_server_count(self):
        return sum(any(name == self._artwork_action for name, _ in
                       get_action_server_names_and_types_by_node(self, node, namespace))
                   for node, namespace in self.get_node_names_and_namespaces())

    # [핵심 기능] 지정한 job_id의 마지막 수신 상태 반환
    def get_status(self, job_id: str) -> JobStatusReply | None:
        with self._lock:
            return self._statuses.get(job_id)

    # [핵심 기능] ROS 비동기 Service를 호출하고 타임아웃 및 job_id 일치 검증
    async def _call(self, client, request, expected_job_id: str, *, timeout_sec=None) -> JobCommandReply:
        if not client.service_is_ready():
            raise ServiceUnavailable("ROS 2 JobManager service unavailable")
        if self._service_server_count(client.srv_name) != 1:
            raise ServiceUnavailable('JobManager 서버가 중복되거나 연결이 미확정입니다. Discovery 설정을 확인하세요.')
        future = client.call_async(request)
        deadline = time.monotonic() + (self.timeout_sec if timeout_sec is None else timeout_sec)
        # Nonblocking poll: executor spins separately and completes ROS future.
        while not future.done():
            if time.monotonic() >= deadline:
                future.cancel()
                # TEAM_SYNC(JobManager): Timeout is NOT cancellation of robot work.
                # Preserve job_id/request_id on retry and query actual job state.
                raise ServiceTimeout("ROS 2 JobManager response timed out; state unconfirmed")
            await asyncio.sleep(0.02)
        try:
            result = future.result()
        except Exception as exc:
            raise ServiceUnavailable("ROS 2 service transport failed") from exc
        if result is None or result.job_id != expected_job_id:
            raise ContractMismatch("JobManager returned an invalid or mismatched job_id")
        return JobCommandReply(
            accepted=bool(result.accepted),
            job_id=result.job_id,
            manager_state=result.state,
            error_code=result.error_code,
            message=result.message,
        )

    # [핵심 기능] 신규 작업 등록 Service 요청 전송
    async def create_job(self, job_id: str, plan_path: str) -> JobCommandReply:
        request = CreateJob.Request()
        request.job_id = job_id
        request.plan_path = plan_path
        return await self._call(self._create_client, request, job_id)

    # [핵심 기능] PAUSE/RESUME/CANCEL Service 요청 전송
    async def control_job(self, job_id: str, command: str, request_id: str) -> JobCommandReply:
        request = ControlJob.Request()
        request.job_id = job_id
        request.command = command
        request.request_id = request_id
        # 정리 명령은 여러 차례 실제 상태를 관측하므로 일반 제어 응답보다 기다립니다.
        return await self._call(self._control_client, request, job_id,
                                timeout_sec=max(self.timeout_sec, 40.) if command == 'REPLACE' else (max(self.timeout_sec, 12.) if command in ('RECONCILE','RESUME') else None))

    async def prepare_artwork(self, body):
        deadline = time.monotonic() + 3.0
        while True:
            count = self._artwork_server_count()
            if count > 1:
                raise ServiceUnavailable('ArtworkPipeline 서버가 중복되었습니다. 외부 Discovery Server와 이전 실행을 확인하세요.')
            if count == 1 and self._artwork.server_is_ready():
                break
            if time.monotonic() >= deadline:
                raise ServiceUnavailable('ArtworkPipeline Action 서버에 연결할 수 없습니다.')
            await asyncio.sleep(0.05)
        goal = PrepareArtwork.Goal()
        for key,value in body.dict().items():
            setattr(goal,key,value)
        async def wait(future, seconds):
            deadline = time.monotonic()+seconds
            while not future.done():
                if time.monotonic()>=deadline:
                    raise ServiceTimeout('이미지 처리 응답 시간 초과입니다. 같은 작업의 파일 상태를 확인하세요.')
                await asyncio.sleep(.02)
            return future.result()
        handle = await wait(self._artwork.send_goal_async(goal),3.)
        if not handle.accepted:
            raise ServiceUnavailable('Pipeline이 사용 중이거나 요청을 거절했습니다.')
        try:
            wrapped = await wait(handle.get_result_async(),140.)
        except ServiceTimeout:
            handle.cancel_goal_async()
            raise
        result=wrapped.result
        if result.job_id != body.job_id:
            raise ContractMismatch('Pipeline 작업 ID가 일치하지 않습니다.')
        if not result.success:
            raise ArtworkFailed(result.error_code+': '+result.message)
        return {key:getattr(result,key) for key in ('job_id','lineart_path','plan_path','preview_path')}

    def destroy_node(self):
        # ActionClient도 Node의 기본 정리 대상에 포함되지 않습니다.
        if self._artwork is not None:
            self._artwork.destroy()
            self._artwork = None
        return super().destroy_node()
