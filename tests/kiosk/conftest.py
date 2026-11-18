"""키오스크 시험은 임시 저장소와 HTTP 모형만 사용하며 실제 Bridge에 연결하지 않습니다."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "ros2_ws/src/art_job_manager", ROOT / "ros2_ws/src/art_kiosk_bridge"):
    sys.path.insert(0, str(path))
