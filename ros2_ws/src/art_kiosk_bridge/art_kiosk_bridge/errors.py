# [파일 역할] KioskBridge 오류 종류
# [동작] 서비스 미연결, 시간 초과, 계약 불일치를 구별해 HTTP 오류로 전달합니다.
# [주의] 시간 초과라고 실제 로봇이 중단된 것은 아닙니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Transport-neutral failures shared by HTTP and ROS layers."""


class BridgeError(Exception):
    """A known, user-reportable bridge failure."""


class ServiceUnavailable(BridgeError):
    """JobManager's ROS service is not currently available."""


class ServiceTimeout(BridgeError):
    """ROS request completion was not confirmed by the deadline."""


class ContractMismatch(BridgeError):
    """The ROS response does not match our agreed contract."""


class ArtworkFailed(BridgeError):
    """Pipeline이 실패 또는 취소 결과를 명시적으로 반환했습니다."""
