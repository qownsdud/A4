# [파일 역할] KioskBridge 통합 회귀 테스트
# [동작] HTTP→ROS 계약, 상태 캐시, 오류 처리, 정지·복구 시나리오를 자동 검증합니다.
# [주의] 테스트를 실행한다고 실제 로봇이 움직이지 않습니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Offline HTTP schema, error and status tests; requires no ROS 2 installation."""

import asyncio

import httpx

from art_kiosk_bridge.errors import ServiceTimeout, ServiceUnavailable
from art_kiosk_bridge.http_api import create_app
from art_kiosk_bridge.schemas import JobCommandReply, JobStatusReply


class FakeBridge:
    def __init__(self):
        self.failure = None
        self.last = None
        self.ready = True
        self.status = None

    # [핵심 기능] JobManager의 생성·제어 Service가 사용 가능한지 확인
    def is_ready(self):
        return self.ready

    # [핵심 기능] 신규 작업 등록 Service 요청 전송
    async def create_job(self, job_id, plan_path):
        self.last = ("create", job_id, plan_path)
        if self.failure:
            raise self.failure
        return JobCommandReply(accepted=True, job_id=job_id, manager_state="DRAWING")

    # [핵심 기능] PAUSE/RESUME/CANCEL Service 요청 전송
    async def control_job(self, job_id, command, request_id):
        self.last = ("control", job_id, command, request_id)
        if self.failure:
            raise self.failure
        return JobCommandReply(accepted=True, job_id=job_id, manager_state="PAUSING")

    # [핵심 기능] 지정한 job_id의 마지막 수신 상태 반환
    def get_status(self, job_id):
        return self.status


def request(bridge, method, path, **kwargs):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(bridge)),
            base_url="http://bridge.test",
        ) as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(run())


# [핵심 기능] pytest: create job and health 조건을 검증
def test_create_job_and_health():
    fake = FakeBridge()
    result = request(fake, "POST", "/bridge/jobs", json={"job_id": "JOB_001", "plan_path": "/tmp/job.json"})
    assert result.status_code == 202
    assert fake.last == ("create", "JOB_001", "/tmp/job.json")
    assert result.json()["manager_state"] == "DRAWING"
    assert request(fake, "GET", "/health").json()["status"] == "ready"


# [핵심 기능] pytest: reject invalid inputs before ros 조건을 검증
def test_reject_invalid_inputs_before_ros():
    fake = FakeBridge()
    result = request(fake, "POST", "/bridge/jobs", json={"job_id": "../bad", "plan_path": "x"})
    assert result.status_code == 422 and fake.last is None
    result = request(fake, "POST", "/bridge/jobs/JOB_001/control", json={"command": "STOP", "request_id": "id1"})
    assert result.status_code == 422


# [핵심 기능] pytest: control ack does not claim paused 조건을 검증
def test_control_ack_does_not_claim_paused():
    fake = FakeBridge()
    result = request(fake, "POST", "/bridge/jobs/JOB_001/control", json={"command": "PAUSE", "request_id": "pause01"})
    assert result.status_code == 202
    assert result.json()["manager_state"] == "PAUSING"
    assert request(fake, "GET", "/bridge/jobs/JOB_001").status_code == 404


# [핵심 기능] pytest: confirmed status is from topic only 조건을 검증
def test_confirmed_status_is_from_topic_only():
    fake = FakeBridge()
    fake.status = JobStatusReply(job_id="JOB_001", state="PAUSED", observed_at_unix=1.0)
    status = request(fake, "GET", "/bridge/jobs/JOB_001")
    assert status.status_code == 200 and status.json()["state"] == "PAUSED"


# [핵심 기능] pytest: timeout and unavailable 조건을 검증
def test_timeout_and_unavailable():
    fake = FakeBridge()
    fake.failure = ServiceUnavailable("mock not online")
    assert request(fake, "POST", "/bridge/jobs", json={"job_id": "A1", "plan_path": "x"}).status_code == 503
    fake.failure = ServiceTimeout("response unconfirmed")
    assert request(fake, "POST", "/bridge/jobs/A1/control", json={"command": "CANCEL", "request_id": "x1"}).status_code == 504
    fake.ready = False
    assert request(fake, "GET", "/health").json()["status"] == "degraded"
