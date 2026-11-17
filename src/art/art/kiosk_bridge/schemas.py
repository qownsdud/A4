# [파일 역할] HTTP 요청/응답 데이터 모양
# [동작] Pydantic으로 요청 본문을 검증하고 JobManager 응답 필드를 정의합니다.
# [주의] 인터페이스 이름을 바꾸면 UI·FastAPI·ROS Bridge를 함께 맞춰야 합니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Provisional HTTP-side schemas; independent from rclpy so tests run offline."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

# TEAM_SYNC(Backend/UI/JobManager): freeze field names, limits, commands and error codes.
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class CreateJobBody(BaseModel):
    job_id: str = Field(min_length=1, max_length=64)
    plan_path: str = Field(min_length=1, max_length=4096)
    # TEAM_SYNC(Backend/Pipeline): path points to job-specific immutable DrawingPlan,
    # NOT confirmed_outputs/latest_lineart.png and NOT a pixel-only strokes JSON.


class ControlJobBody(BaseModel):
    command: Literal["PAUSE", "RESUME", "CANCEL"]
    request_id: str = Field(min_length=1, max_length=64)


class JobCommandReply(BaseModel):
    accepted: bool
    job_id: str
    manager_state: str
    error_code: str = ""
    message: str = ""
    # TEAM_SYNC(UI): accepted=true is NOT proof of physical PAUSE/STOP.


class JobStatusReply(BaseModel):
    job_id: str
    state: str
    completed_strokes: int = 0
    total_strokes: int = 0
    current_pen: str = ""
    error_code: str = ""
    message: str = ""
    observed_at_unix: float
    # TEAM_SYNC(JobManager/UI): define stale-state policy and polling frequency.


def valid_job_id(value: str) -> bool:
    return bool(JOB_ID_PATTERN.fullmatch(value))


def valid_request_id(value: str) -> bool:
    return bool(REQUEST_ID_PATTERN.fullmatch(value))

class PrepareArtworkBody(BaseModel):
    job_id: str = Field(min_length=1,max_length=64)
    stage: Literal['LINEART','PLAN']
    input_path: str = Field(min_length=1,max_length=4096)
    method: Literal['cv','dl'] = 'cv'
    paper: Literal['a4','postcard','square'] = 'a4'
    detail: Literal['high','medium','low'] = 'medium'
    seed: int = 42
    text: str = Field(default='',max_length=120)
    class Config:
        extra = 'forbid'
