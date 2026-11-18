"""관리자 동일 출처 검사와 고정 loopback Bridge 중계. 사진 변환·로봇 구동은 수행하지 않습니다."""

from __future__ import annotations

import math
import os
from pathlib import Path
import re
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
import httpx
from pydantic import BaseModel, Field, StrictBool, StrictStr, ValidationError, conint, validator

router = APIRouter()
_BRIDGE_PORT = int(os.environ.get('ART_BRIDGE_PORT', '8001'))
if not 1 <= _BRIDGE_PORT <= 65535:
    raise ValueError('ART_BRIDGE_PORT는 1~65535 범위여야 합니다.')
BRIDGE_URL = f"http://127.0.0.1:{_BRIDGE_PORT}"
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
STATES = Literal["QUEUED", "DISPATCHING", "DRAWING", "PAUSING", "PAUSED", "RESUMING",
                 "STOPPING", "STOPPED", "COMPLETED", "RECOVERY_REQUIRED"]


class ControlBody(BaseModel):
    command: Literal["PAUSE", "RESUME", "CANCEL"]
    request_id: str = Field(min_length=1, max_length=64)

    @validator("request_id")
    def exact_request_id(cls, value):
        if not re.fullmatch(ID_PATTERN, value):
            raise ValueError("잘못된 요청 ID")
        return value

    class Config:
        extra = "forbid"


class CreateBody(BaseModel):
    job_id: str = Field(min_length=1, max_length=64)
    plan_path: str = Field(min_length=1, max_length=4096)

    @validator("job_id")
    def exact_job_id(cls, value):
        if not re.fullmatch(ID_PATTERN, value):
            raise ValueError("잘못된 작업 ID")
        return value

    class Config:
        extra = "forbid"


class StatusBody(BaseModel):
    job_id: StrictStr
    state: STATES
    completed_strokes: conint(strict=True, ge=0)
    total_strokes: conint(strict=True, ge=1)
    current_pen: StrictStr
    error_code: StrictStr
    message: StrictStr
    observed_at_unix: float

    @validator("observed_at_unix")
    def finite_time(cls, value):
        if not math.isfinite(value):
            raise ValueError("유효하지 않은 관측 시각")
        return value


class CommandReply(BaseModel):
    accepted: StrictBool
    job_id: StrictStr
    manager_state: STATES
    error_code: StrictStr = ""
    message: StrictStr = ""


def require_same_origin(request: Request) -> None:
    # 운영 요청에 따라 인증키를 요구하지 않습니다. 교차 출처 요청 차단은 유지합니다.
    origin = request.headers.get("origin")
    if ((origin and origin != str(request.base_url).rstrip("/"))
            or request.headers.get("sec-fetch-site") == "cross-site"):
        raise HTTPException(403, "동일 출처의 관리자 요청만 허용합니다.")


def check_id(job_id: str) -> None:
    if not re.fullmatch(ID_PATTERN, job_id):
        raise HTTPException(422, "잘못된 작업 ID입니다.")


async def bridge_request(request: Request, method: str, path: str, *, body=None, timeout=5.0):
    # 주소는 고정합니다. 요청 본문이나 URL로 중계 대상을 변경할 수 없습니다.
    try:
        async with httpx.AsyncClient(
            base_url=BRIDGE_URL, timeout=httpx.Timeout(timeout), trust_env=False,
            transport=getattr(request.app.state, "bridge_transport", None),
        ) as client:
            response = await client.request(method, path, json=body)
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Bridge 응답 시간 초과: 실제 작업 상태는 미확정입니다. 같은 요청 ID를 유지하세요.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(503, "Bridge 연결 끊김: 실제 로봇 상태를 확인할 수 없습니다.") from exc
    if response.status_code >= 400:
        # 자동 재시도하지 않습니다. 특히 504는 원격 작업 취소를 뜻하지 않습니다.
        try:
            detail = response.json().get("detail", "Bridge 요청 실패")
        except (ValueError, AttributeError):
            detail = "Bridge 요청 실패"
        code = response.status_code if response.status_code in (404, 409, 422, 502, 503, 504) else 502
        raise HTTPException(code, detail)
    if response.status_code not in (200, 202):
        raise HTTPException(502, "Bridge 응답 형식이 일치하지 않습니다.")
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("응답 객체 필요")
        return data
    except ValueError as exc:
        raise HTTPException(502, "Bridge JSON 응답이 잘못되었습니다.") from exc


async def manager_ready(request: Request) -> None:
    health = await bridge_request(request, "GET", "/health")
    if health.get("job_manager_reachable") is not True:
        raise HTTPException(503, "JobManager 연결 끊김: 캐시된 상태를 현재 상태로 확정할 수 없습니다.")


async def observed_status(request: Request, job_id: str):
    check_id(job_id)
    await manager_ready(request)
    data = await bridge_request(request, "GET", f"/bridge/jobs/{job_id}")
    try:
        status = StatusBody(**data)
        if status.job_id != job_id or status.completed_strokes > status.total_strokes:
            raise ValueError("작업 ID 또는 완료 획 불일치")
    except (ValidationError, ValueError) as exc:
        raise HTTPException(502, "Bridge 상태 응답이 계약과 일치하지 않습니다.") from exc
    age = time.time() - status.observed_at_unix
    # 서버 설정이 잘못되어도 오래된 정보를 최신으로 표시하지 않습니다.
    try:
        max_age = float(os.environ.get("ART_STATUS_MAX_AGE_SEC", "5"))
        if not math.isfinite(max_age) or max_age <= 0:
            raise ValueError("양수 필요")
    except ValueError as exc:
        raise HTTPException(503, "상태 유효 시간 설정이 잘못되었습니다.") from exc
    stale = age > max_age or age < -1
    return {**status.dict(), "stale": stale, "age_sec": max(0, age),
            "valid_for_sec": max(0, max_age - max(0, age)) if not stale else 0,
            "state_confirmed": not stale and status.state != "RECOVERY_REQUIRED"}


@router.get("/api/kiosk/capabilities")
def capabilities():
    return {"photo_to_drawing_plan": True, "automatic_job_start": False,
            "user_draw_confirmation": True, "single_current_job": True,
            "admin_prepared_plan_submission": False,
            "message": "사진·영문 문구의 경로를 자동 생성하고 사용자 그리기 승인 후 작업을 등록합니다."}


@router.get("/api/kiosk/jobs/{job_id}")
async def public_job_status(job_id: str, request: Request):
    return await observed_status(request, job_id)


@router.get("/api/admin/session", dependencies=[Depends(require_same_origin)])
def admin_session():
    return {"role": "admin"}


@router.get("/api/admin/jobs/{job_id}", dependencies=[Depends(require_same_origin)])
async def admin_job_status(job_id: str, request: Request):
    return await observed_status(request, job_id)


def command_reply(data, job_id):
    try:
        reply = CommandReply(**data)
        if reply.job_id != job_id or not reply.accepted:
            raise ValueError("작업 응답 불일치")
        # 수락과 물리 정지 완료를 별도 필드로 표현합니다. 확정은 상태 조회로만 합니다.
        return {**reply.dict(), "physical_state_confirmed": False,
                "notice": "요청이 수락되었습니다. 실제 정지·완료는 상태 조회에서 별도로 확인하세요."}
    except (ValidationError, ValueError) as exc:
        raise HTTPException(502, "Bridge 명령 응답이 계약과 일치하지 않습니다.") from exc


@router.post("/api/admin/jobs/{job_id}/control", status_code=202,
             dependencies=[Depends(require_same_origin)])
async def control_job(job_id: str, body: ControlBody, request: Request):
    status = await observed_status(request, job_id)
    if status["stale"]:
        raise HTTPException(409, "오래된 상태입니다. 제어 요청을 보내지 않았습니다. 연결과 실제 상태를 확인하세요.")
    data = await bridge_request(request, "POST", f"/bridge/jobs/{job_id}/control", body=body.dict())
    # request_id를 변환하거나 생성하지 않습니다. 중복 처리는 Manager의 영속 receipt를 사용합니다.
    return command_reply(data, job_id)


@router.post("/api/admin/jobs", status_code=202, dependencies=[Depends(require_same_origin)])
async def create_prepared_job(body: CreateBody, request: Request):
    from .workflow import guard_legacy_registration
    guard_legacy_registration()
    # 사진→계획 변환기를 가장하지 않고, 이미 만들어진 계획만 기존 Manager에 전달합니다.
    try:
        root = Path(os.environ.get("ART_JOB_PLAN_ROOT", str(Path.home() / "A4/data/jobs"))).expanduser().resolve(strict=True)
        raw_path = Path(body.plan_path)
        if not raw_path.is_absolute():
            raise ValueError("절대 경로 필요")
        path = raw_path.resolve(strict=True)
        if (root not in path.parents or path.parent.name != body.job_id
                or not path.is_file() or path.suffix.lower() != ".json"):
            raise ValueError("허용되지 않은 계획 경로")
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(422, "계획 루트 안의 작업별 JSON 절대 경로가 필요합니다.") from exc
    await manager_ready(request)
    data = await bridge_request(request, "POST", "/bridge/jobs",
                                body={"job_id": body.job_id, "plan_path": str(path)})
    # JSON 스키마·좌표·SHA의 최종 검증은 기존 JobManager의 load_plan이 수행합니다.
    return command_reply(data, body.job_id)
