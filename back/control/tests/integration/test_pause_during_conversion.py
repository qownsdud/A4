# [파일 역할] KioskBridge 통합 회귀 테스트
# [동작] HTTP→ROS 계약, 상태 캐시, 오류 처리, 정지·복구 시나리오를 자동 검증합니다.
# [주의] 테스트를 실행한다고 실제 로봇이 움직이지 않습니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Opt-in LIVE kiosk responsiveness probe. It does NOT actuate the robot.

TEAM_SYNC(Backend/UI): current server.py has no PAUSE endpoint. This test checks
its request-loop responsiveness via /api/health during photo conversion only.
The actual HMI PAUSE→Bridge→robot stop test must be added after integration.
"""

import asyncio
import os
import time
from pathlib import Path

import httpx
import pytest


@pytest.mark.skipif(os.getenv("RUN_LIVE_KIOSK_TEST") != "1", reason="Opt in using RUN_LIVE_KIOSK_TEST=1")
# [핵심 기능] pytest: kiosk stays responsive during photo conversion 조건을 검증
def test_kiosk_stays_responsive_during_photo_conversion():
    photo_path = Path(os.getenv("TEST_PHOTO_PATH", ""))
    if not photo_path.is_file():
        pytest.skip("Set TEST_PHOTO_PATH to a real test photo")
    url = os.getenv("KIOSK_BASE_URL", "http://127.0.0.1:8000")
    limit_sec = float(os.getenv("KIOSK_HEALTH_LATENCY_LIMIT", "1.0"))

    async def probe():
        async with httpx.AsyncClient(timeout=130.0) as client:
            upload = asyncio.create_task(client.post(
                url + "/api/kiosk/photo",
                data={"detail": "medium", "paper": "a4"},
                files={"photo": (photo_path.name, photo_path.read_bytes(), "image/jpeg")},
            ))
            await asyncio.sleep(0.15)
            if upload.done():
                pytest.skip("Photo conversion finished before concurrency probe")
            start = time.monotonic()
            try:
                health = await asyncio.wait_for(client.get(url + "/api/health"), timeout=limit_sec)
            except asyncio.TimeoutError:
                upload.cancel()
                await asyncio.gather(upload, return_exceptions=True)
                pytest.fail("Health request blocked while image conversion ran")
            elapsed = time.monotonic() - start
            await upload
            assert health.status_code == 200
            assert elapsed < limit_sec
    asyncio.run(probe())
