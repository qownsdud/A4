"""설치 전 ROS2 소스 패키지의 시험 경로."""
from pathlib import Path
import sys
for directory in (Path(__file__).resolve().parent/'ros2_ws/src').glob('art_*'):
    if (directory/'setup.py').exists():
        sys.path.insert(0,str(directory))

# HTTP 회귀 시험은 데이터베이스 대신 명시적인 테스트 상태를 주입합니다.
sys.path.insert(0,str(Path(__file__).resolve().parent/'tests'))
