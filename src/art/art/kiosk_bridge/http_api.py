# [파일 역할] KioskBridge HTTP API 담당
# [동작] GET /health, POST /bridge/jobs, POST /bridge/jobs/{id}/control, GET /bridge/jobs/{id} 를 제공합니다.
# [주의] 원래 FastAPI 서버와 별도로 실행하는 HTTP 수신부입니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""An independent HTTP endpoint called by the existing FastAPI server.

No ROS import here: dependency injection allows complete standalone HTTP tests.
"""

from __future__ import annotations

import logging
from typing import Protocol

from fastapi import FastAPI, HTTPException

from .errors import ContractMismatch, ServiceTimeout, ServiceUnavailable
from .schemas import (
    PrepareArtworkBody,
    ControlJobBody,
    CreateJobBody,
    JobCommandReply,
    JobStatusReply,
    valid_job_id,
    valid_request_id,
)

logger = logging.getLogger(__name__)


class BridgePort(Protocol):
    # [핵심 기능] 신규 작업 등록 Service 요청 전송
    async def create_job(self, job_id: str, plan_path: str) -> JobCommandReply: ...
    # [핵심 기능] PAUSE/RESUME/CANCEL Service 요청 전송
    async def control_job(self, job_id: str, command: str, request_id: str) -> JobCommandReply: ...
    # [핵심 기능] 지정한 job_id의 마지막 수신 상태 반환
    def get_status(self, job_id: str) -> JobStatusReply | None: ...
    # [핵심 기능] JobManager의 생성·제어 Service가 사용 가능한지 확인
    def is_ready(self) -> bool: ...


# [핵심 기능] Bridge REST API 라우트를 구성
def create_app(bridge: BridgePort) -> FastAPI:
    app = FastAPI(title="A4 ROS 2 Kiosk Bridge", version="0.1.0")

    @app.get("/health")
    # [핵심 기능] 브리지와 JobManager Service 연결 여부 확인
    def health() -> dict[str, object]:
        # TEAM_SYNC(Operations): readiness is a JobManager service presence check,
        # not proof that the robot is safe/ready to draw.
        ready = bridge.is_ready()
        return {"status": "ready" if ready else "degraded", "job_manager_reachable": ready}

    @app.post('/bridge/artwork')
    async def prepare_artwork(body: PrepareArtworkBody):
        if not valid_job_id(body.job_id):
            raise HTTPException(422,'잘못된 작업 ID입니다.')
        try:
            return await bridge.prepare_artwork(body)
        except ServiceUnavailable as exc:
            raise HTTPException(503,str(exc)) from exc
        except ServiceTimeout as exc:
            raise HTTPException(504,str(exc)) from exc
        except ContractMismatch as exc:
            raise HTTPException(502,str(exc)) from exc

    @app.post("/bridge/jobs", response_model=JobCommandReply, status_code=202)
    # [핵심 기능] 신규 작업 등록 Service 요청 전송
    async def create_job(body: CreateJobBody) -> JobCommandReply:
        # TEAM_SYNC(Backend): FastAPI must send a stable job_id and DrawingPlan path.
        if not valid_job_id(body.job_id):
            raise HTTPException(status_code=422, detail="Invalid job_id format")
        try:
            response = await bridge.create_job(body.job_id, body.plan_path)
        except ServiceUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ServiceTimeout as exc:
            # TIMEOUT is uncertain; NEVER retry with a fresh job_id automatically.
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except ContractMismatch as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if not response.accepted:
            raise HTTPException(status_code=409, detail=response.dict())
        return response

    @app.post("/bridge/jobs/{job_id}/control", response_model=JobCommandReply, status_code=202)
    # [핵심 기능] PAUSE/RESUME/CANCEL Service 요청 전송
    async def control_job(job_id: str, body: ControlJobBody) -> JobCommandReply:
        # TEAM_SYNC(UI/JobManager/Robot): action names and confirmed status semantics.
        if not valid_job_id(job_id) or not valid_request_id(body.request_id):
            raise HTTPException(status_code=422, detail="Invalid job_id or request_id")
        try:
            response = await bridge.control_job(job_id, body.command, body.request_id)
        except ServiceUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ServiceTimeout as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except ContractMismatch as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if not response.accepted:
            raise HTTPException(status_code=409, detail=response.dict())
        # An accepted PAUSE is not equivalent to PAUSED (actual robot stop).
        return response

    @app.get("/bridge/jobs/{job_id}", response_model=JobStatusReply)
    # [핵심 기능] 최근 관측된 JobStatus 반환 (미확인 상태를 임의 추측하지 않음)
    def job_status(job_id: str) -> JobStatusReply:
        if not valid_job_id(job_id):
            raise HTTPException(status_code=422, detail="Invalid job_id format")
        result = bridge.get_status(job_id)
        if result is None:
            # No status event yet is unknown, NOT a confirmed stop/completion.
            raise HTTPException(status_code=404, detail="No confirmed status event for this job")
        return result

    return app
