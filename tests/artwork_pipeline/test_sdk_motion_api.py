"""설치된 두산 메시지 타입과 SDK 관측값의 호환성을 검증합니다."""

from concurrent.futures import Future
from types import SimpleNamespace
import numpy as np
import pytest
from art_artwork_pipeline.live_control import DsrMotionApi


def test_protective_stop_can_be_observed_when_stop_service_rejects():
    pytest.importorskip(
        "dsr_msgs2.srv", reason="두산 워크스페이스 overlay가 필요합니다."
    )
    state = {"value": 5}

    class Client:
        def wait_for_service(self, timeout_sec):
            return True

        def call_async(self, request):
            assert request.stop_mode == 2
            future = Future()
            future.set_result(SimpleNamespace(success=False))
            return future

    node = SimpleNamespace(create_client=lambda *a, **kw: Client())
    sdk = SimpleNamespace(
        get_robot_state=lambda: state["value"],
        get_current_posx=lambda ref: (np.zeros(6), 0),
        get_current_velx=lambda ref: np.zeros(6),
        check_motion=lambda: 0,
    )
    api = DsrMotionApi(node, sdk)
    api.rclpy = SimpleNamespace(spin_until_future_complete=lambda *a, **kw: None)
    api.stop()
    state["value"] = 1
    with pytest.raises(RuntimeError, match="미확정"):
        api.stop()
    assert api.pose() == [0.0] * 6
