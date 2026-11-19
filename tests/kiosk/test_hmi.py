"""인증·권한·중복·연결·상태 신선도·사진 처리 회귀 시험."""

import asyncio
import io
import json
from pathlib import Path
import subprocess
import threading
import time

import httpx
from PIL import Image
import pytest

from art_kiosk import server
from art_job_manager.production_engine import ProductionEngine
from art_kiosk_bridge.http_api import create_app
from art_kiosk_bridge.schemas import JobCommandReply, JobStatusReply

AUTH = {}


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (32, 48), "white").save(output, "PNG")
    return output.getvalue()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("ART_STATUS_MAX_AGE_SEC", "5")
    monkeypatch.setenv("ART_JOB_PLAN_ROOT", str(tmp_path / "plans"))
    monkeypatch.setenv('ART_LINEART_METHOD','cv')

    def unexpected(request):
        raise AssertionError(f"예상하지 않은 Bridge 호출: {request.method} {request.url.path}")

    monkeypatch.setattr(server.app.state, "bridge_transport", httpx.MockTransport(unexpected), raising=False)


def request(method, path, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                     base_url="http://kiosk.test") as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(run())


def status(**updates):
    return {"job_id": "J1", "state": "DRAWING", "completed_strokes": 0,
            "total_strokes": 2, "current_pen": "PEN_1", "error_code": "", "message": "",
            "observed_at_unix": time.time(), **updates}


def mock_bridge(monkeypatch, *, snapshot=None, ready=True, control_code=202):
    calls = []

    def handle(req):
        assert req.url.host == "127.0.0.1" and req.url.port == 8001
        # 관리자 자격 증명은 Bridge에 전달하지 않습니다.
        assert "authorization" not in req.headers
        calls.append(req)
        if req.url.path == "/health":
            return httpx.Response(200, json={"job_manager_reachable": ready})
        if req.method == "GET":
            return httpx.Response(200, json=snapshot if snapshot is not None else status())
        if control_code != 202:
            return httpx.Response(control_code, json={"detail": "요청 결과 미확정"})
        return httpx.Response(202, json={"accepted": True, "job_id": "J1", "manager_state": "PAUSING"})

    monkeypatch.setattr(server.app.state, "bridge_transport", httpx.MockTransport(handle))
    return calls


@pytest.mark.parametrize("path,body", [
    ("/api/admin/jobs/J1/control", {"command": "PAUSE", "request_id": "P1"}),
    ("/api/admin/jobs", {"job_id": "J1", "plan_path": "/tmp/J1/plan.json"}),
])
@pytest.mark.parametrize("headers", [{"Origin": "http://evil.test"},
    {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}])
def test_cross_origin_commands_never_reach_bridge(path, body, headers):
    result = request("POST", path, json=body, headers=headers)
    assert result.status_code == 403
    assert result.headers["cache-control"] == "no-store"


def test_admin_requires_no_key(monkeypatch):
    monkeypatch.delenv("ART_ADMIN_TOKEN", raising=False)
    assert request("GET", "/api/admin/session").json() == {"role": "admin"}
    monkeypatch.setenv("ART_ADMIN_TOKEN", "short")
    assert request("GET", "/api/admin/session").status_code == 200
    mock_bridge(monkeypatch)
    assert request("GET", "/api/admin/jobs/J1").status_code == 200
    page = request("GET", "/admin").text
    assert 'id="adminToken"' not in page and 'id="loginForm"' not in page


def test_cross_origin_admin_request_rejected():
    assert request("GET", "/api/admin/session", headers={**AUTH, "Origin": "http://evil.test"}).status_code == 403
    assert request("GET", "/api/admin/session", headers={**AUTH, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert request("GET", "/api/admin/session", headers={**AUTH, "Origin": "http://kiosk.test"}).status_code == 200


def test_user_screen_has_no_robot_controls_or_bridge_calls():
    page = request("GET", "/").text
    script = request("GET", "/static/app.js").text
    assert "jobProgress" in page
    for text in ("data-command", "PAUSE ·", "RESUME ·", "CANCEL ·"):
        assert text not in page
    for name in ("app.js", "admin.js"):
        js = request("GET", f"/static/{name}").text
        assert "127.0.0.1:8001" not in js and "/bridge/" not in js
    assert "innerHTML" not in script
    assert request("GET", "/admin").status_code == 200
    assert "connect-src 'self'" in request("GET", "/admin").headers["content-security-policy"]
    assert request("POST", "/api/kiosk/jobs/J1/control", json={}).status_code in (404, 405)
    capabilities = request("GET", "/api/kiosk/capabilities").json()
    assert capabilities["photo_to_drawing_plan"] is True
    assert capabilities["automatic_job_start"] is False


def test_command_acceptance_does_not_claim_physical_pause(monkeypatch):
    calls = mock_bridge(monkeypatch)
    result = request("POST", "/api/admin/jobs/J1/control", headers=AUTH,
                     json={"command": "PAUSE", "request_id": "P1"})
    assert result.status_code == 202
    assert result.json()["manager_state"] == "PAUSING"
    assert result.json()["physical_state_confirmed"] is False
    assert json.loads(calls[-1].content) == {"command": "PAUSE", "request_id": "P1"}
    observed = request("GET", "/api/kiosk/jobs/J1").json()
    assert observed["state"] == "DRAWING"


@pytest.mark.parametrize("age", [30, -20])
def test_stale_and_future_status_never_confirms_or_controls(monkeypatch, age):
    calls = mock_bridge(monkeypatch, snapshot=status(state="PAUSED", observed_at_unix=time.time() - age))
    reply = request("GET", "/api/kiosk/jobs/J1")
    assert reply.status_code == 200 and reply.json()["stale"] is True
    assert reply.json()["state_confirmed"] is False
    result = request("POST", "/api/admin/jobs/J1/control", headers=AUTH,
                     json={"command": "RESUME", "request_id": "R1"})
    assert result.status_code == 409
    assert all(call.method == "GET" for call in calls)


def test_manager_disconnect_does_not_expose_cached_paused_as_current(monkeypatch):
    calls = mock_bridge(monkeypatch, snapshot=status(state="PAUSED"), ready=False)
    assert request("GET", "/api/kiosk/jobs/J1").status_code == 503
    assert request("POST", "/api/admin/jobs/J1/control", headers=AUTH,
                   json={"command": "RESUME", "request_id": "R1"}).status_code == 503
    assert all(call.url.path == "/health" for call in calls)


@pytest.mark.parametrize("exception,code", [(httpx.ConnectError, 503), (httpx.ReadTimeout, 504)])
def test_bridge_transport_disconnect_or_timeout(monkeypatch, exception, code):
    calls = []

    def handle(req):
        calls.append(req)
        raise exception("모의 연결 오류", request=req)

    monkeypatch.setattr(server.app.state, "bridge_transport", httpx.MockTransport(handle))
    assert request("GET", "/api/kiosk/jobs/J1").status_code == code
    assert len(calls) == 1


@pytest.mark.parametrize("code", [409, 503, 504])
def test_control_failure_is_preserved_without_auto_retry(monkeypatch, code):
    calls = mock_bridge(monkeypatch, control_code=code)
    result = request("POST", "/api/admin/jobs/J1/control", headers=AUTH,
                     json={"command": "CANCEL", "request_id": "C1"})
    assert result.status_code == code
    assert len([call for call in calls if call.method == "POST"]) == 1


@pytest.mark.parametrize("changes", [{"job_id": "OTHER"}, {"completed_strokes": 3},
                                    {"state": "INVALID"}, {"observed_at_unix": "NaN"},
                                    {"total_strokes": "2"}])
def test_invalid_status_response_rejected(monkeypatch, changes):
    mock_bridge(monkeypatch, snapshot=status(**changes))
    assert request("GET", "/api/kiosk/jobs/J1").status_code == 502


def test_recovery_status_is_unconfirmed(monkeypatch):
    mock_bridge(monkeypatch, snapshot=status(state="RECOVERY_REQUIRED"))
    assert request("GET", "/api/kiosk/jobs/J1").json()["state_confirmed"] is False


@pytest.mark.parametrize("body", [{"command": "STOP", "request_id": "P1"},
                                 {"command": "PAUSE", "request_id": "../bad"},
                                 {"command": "PAUSE", "request_id": "P1\n"},
                                 {"command": "PAUSE", "request_id": "P1", "role": "admin"}])
def test_invalid_control_body_never_reaches_bridge(body):
    assert request("POST", "/api/admin/jobs/J1/control", headers=AUTH, json=body).status_code == 422


def test_confirm_saves_png_only_and_retains_previous_image():
    paths = []
    for index in range(2):
        result = request("POST", "/api/kiosk/confirm", files={"image": ("line.png", png_bytes(), "image/png")},
                         data={"paper": "a4", "engine": "test"})
        assert result.status_code == 200
        assert result.json()["drawing_plan_created"] is False
        assert result.json()["job_started"] is False
        paths.append(Path(result.json()["latest_file"]))
    assert paths[0] != paths[1]
    assert all(path.is_file() for path in paths)
    assert request("GET", "/api/kiosk/latest").json()["width"] == 32
    assert request("POST", "/api/kiosk/confirm", files={"image": ("bad.png", b"invalid")}).status_code == 400


def write_plan(root, job_id="J1"):
    target = root / job_id / "drawing_plan.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"schema_version": "0.1", "job_id": job_id,
        "paper_mm": {"width": 210, "height": 297}, "strokes": [
            {"stroke_id": 1, "pen_id": "PEN_1", "points_mm": [[10, 20], [30, 40]]},
            {"stroke_id": 2, "pen_id": "PEN_1", "points_mm": [[30, 40], [50, 60]]},
        ]}), encoding="utf-8")
    return target


class EngineBridge:
    """기존 Bridge HTTP 계약과 실제 ProductionEngine을 연결하는 ROS 비의존 어댑터."""

    def __init__(self, engine):
        self.engine = engine

    def is_ready(self):
        return True

    def get_status(self, job_id):
        row = self.engine.status(job_id)
        return JobStatusReply(**row, observed_at_unix=time.time()) if row else None

    async def create_job(self, job_id, plan_path):
        result = self.engine.create_job(job_id, plan_path)
        return JobCommandReply(accepted=result.accepted, job_id=result.job_id, manager_state=result.state,
                               error_code=result.error_code, message=result.message)

    async def control_job(self, job_id, command, request_id):
        result = self.engine.control_job(job_id, command, request_id)
        return JobCommandReply(accepted=result.accepted, job_id=result.job_id, manager_state=result.state,
                               error_code=result.error_code, message=result.message)


def test_prepared_job_and_duplicate_control_use_real_manager_rules(monkeypatch, tmp_path):
    root = tmp_path / "plans"
    plan = write_plan(root)
    engine = ProductionEngine(tmp_path / "jobs.db", plan_root=root)
    monkeypatch.setattr(server.app.state, "bridge_transport", httpx.ASGITransport(app=create_app(EngineBridge(engine))))
    try:
        create = request("POST", "/api/admin/jobs", headers=AUTH,
                         json={"job_id": "J1", "plan_path": str(plan)})
        assert create.status_code == 202 and create.json()["manager_state"] == "QUEUED"
        assert request("POST", "/api/admin/jobs", headers=AUTH,
                       json={"job_id": "J1", "plan_path": str(plan)}).status_code == 409
        engine.prepare_dispatch("J1")
        engine.on_controller_started("J1")
        body = {"command": "PAUSE", "request_id": "P1"}
        for _ in range(2):
            result = request("POST", "/api/admin/jobs/J1/control", headers=AUTH, json=body)
            assert result.status_code == 202 and result.json()["manager_state"] == "PAUSING"
        with engine.repo.transaction() as con:
            assert con.execute("SELECT count(*) FROM command_receipts").fetchone()[0] == 1
        conflict = request("POST", "/api/admin/jobs/J1/control", headers=AUTH,
                           json={"command": "CANCEL", "request_id": "P1"})
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["error_code"] == "REQUEST_ID_CONFLICT"
        assert engine.on_action_result("J1", ros_status=5, success=False, final_state="INTERRUPTED_SAFE",
                                       completed_strokes=0, pen_up_confirmed=True)
        assert request("GET", "/api/kiosk/jobs/J1").json()["state"] == "PAUSED"
        resumed = request("POST", "/api/admin/jobs/J1/control", headers=AUTH,
                          json={"command": "RESUME", "request_id": "R1"})
        assert resumed.status_code == 202 and resumed.json()["manager_state"] == "QUEUED"
        cancelled = request("POST", "/api/admin/jobs/J1/control", headers=AUTH,
                            json={"command": "CANCEL", "request_id": "C1"})
        assert cancelled.status_code == 202 and cancelled.json()["manager_state"] == "STOPPED"
    finally:
        engine.close()


def test_prepared_plan_still_validated_by_manager(monkeypatch, tmp_path):
    root = tmp_path / "plans"
    plan = write_plan(root)
    plan.write_text("[]", encoding="utf-8")
    engine = ProductionEngine(tmp_path / "jobs.db", plan_root=root)
    monkeypatch.setattr(server.app.state, "bridge_transport", httpx.ASGITransport(app=create_app(EngineBridge(engine))))
    try:
        result = request("POST", "/api/admin/jobs", headers=AUTH,
                         json={"job_id": "J1", "plan_path": str(plan)})
        assert result.status_code == 409
        assert result.json()["detail"]["error_code"] == "PLAN_SCHEMA_OR_ID_MISMATCH"
        assert engine.statuses() == []
    finally:
        engine.close()


def test_lost_control_response_replays_committed_receipt(monkeypatch, tmp_path):
    root = tmp_path / "plans"
    plan = write_plan(root)
    engine = ProductionEngine(tmp_path / "jobs.db", plan_root=root)
    engine.create_job("J1", str(plan))
    engine.prepare_dispatch("J1")
    engine.on_controller_started("J1")

    class LostResponseTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.ASGITransport(app=create_app(EngineBridge(engine)))
            self.lost = False
            self.sent_ids = []

        async def handle_async_request(self, req):
            response = await self.inner.handle_async_request(req)
            if req.method == "POST":
                self.sent_ids.append(json.loads(req.content)["request_id"])
                if not self.lost:
                    self.lost = True
                    # Manager 반영 후 응답만 유실된 상황입니다.
                    raise httpx.ReadTimeout("모의 응답 유실", request=req)
            return response

    transport = LostResponseTransport()
    monkeypatch.setattr(server.app.state, "bridge_transport", transport)
    try:
        body = {"command": "PAUSE", "request_id": "P_LOST"}
        assert request("POST", "/api/admin/jobs/J1/control", headers=AUTH, json=body).status_code == 504
        assert engine.status("J1")["state"] == "PAUSING"
        replay = request("POST", "/api/admin/jobs/J1/control", headers=AUTH, json=body)
        assert replay.status_code == 202
        assert replay.json()["physical_state_confirmed"] is False
        assert transport.sent_ids == ["P_LOST", "P_LOST"]
        with engine.repo.transaction() as con:
            assert con.execute("SELECT count(*) FROM command_receipts").fetchone()[0] == 1
    finally:
        engine.close()


def test_outside_root_or_relative_plan_never_forwarded(tmp_path):
    plan = write_plan(tmp_path / "plans")
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    link = plan.parent / "link.json"
    link.symlink_to(outside)
    for path in ("relative.json", str(outside), str(link)):
        assert request("POST", "/api/admin/jobs", headers=AUTH,
                       json={"job_id": "J1", "plan_path": path}).status_code == 422


def test_photo_conversion_keeps_hmi_responsive(monkeypatch, tmp_path):
    started, release = threading.Event(), threading.Event()

    async def convert(request, body):
        started.set()
        assert await asyncio.to_thread(release.wait, 3), "사진 변환 모형 해제 시간 초과"
        directory = Path(body['input_path']).parent
        (directory/'lineart.png').write_bytes(png_bytes())
        return dict(job_id=body['job_id'],lineart_path=str(directory/'lineart.png'))

    monkeypatch.setattr(server, 'request_pipeline', convert)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://kiosk.test") as client:
            photo = asyncio.create_task(client.post("/api/kiosk/photo", files={"photo": ("photo.png", png_bytes(), "image/png")}))
            try:
                assert await asyncio.to_thread(started.wait, 2)
                session = await asyncio.wait_for(client.get("/api/admin/session", headers=AUTH), timeout=1)
                assert session.status_code == 200
            finally:
                release.set()
            result = await photo
            assert result.status_code == 200
            assert result.headers["content-type"] == "image/png"
            assert result.headers["x-image-size"] == "32x48"
            assert result.headers["x-engine"] == "cv (medium)"

    asyncio.run(run())


def test_photo_validation_and_conversion_timeout(monkeypatch, tmp_path):
    assert request("POST", "/api/kiosk/photo", files={"photo": ("x.png", png_bytes())},
                   data={"detail": "invalid"}).status_code == 400

    async def timeout(*args, **kwargs):
        from fastapi import HTTPException
        raise HTTPException(504,'모의 Pipeline 시간 초과')

    monkeypatch.setattr(server, 'request_pipeline', timeout)
    assert request("POST", "/api/kiosk/photo", files={"photo": ("x.png", png_bytes())}).status_code == 504
