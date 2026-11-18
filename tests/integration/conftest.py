# [파일 역할] pytest 테스트 준비
# [동작] 테스트 실행 때 Python 모듈 경로와 fixture 등을 준비합니다.
# [주의] 파일을 직접 실행하지 않고 pytest를 통해 사용합니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Make the unbuilt bridge Python package importable for offline HTTP tests."""

import sys
from pathlib import Path

BRIDGE_SOURCE = Path(__file__).resolve().parents[2] / "ros2_ws" / "src" / "art_kiosk_bridge"
sys.path.insert(0, str(BRIDGE_SOURCE))
