#!/usr/bin/env bash
# ROS Python과 분리된 선화 환경을 설치합니다. 모델 파일은 내려받지 않습니다.
set -euo pipefail
A4_REPOSITORY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
A4_LINEART_ENV="${ART_LINEART_ENV:-$HOME/.venvs/a4-lineart}"
python3 -m venv "$A4_LINEART_ENV"
env -u PYTHONPATH "$A4_LINEART_ENV/bin/python" -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cpu
env -u PYTHONPATH "$A4_LINEART_ENV/bin/python" -m pip install -r "$A4_REPOSITORY_DIR/ros2_ws/src/art_artwork_pipeline/requirements-dl-lock.txt"
env -u PYTHONPATH "$A4_LINEART_ENV/bin/python" -m pip install --no-deps -e "$A4_REPOSITORY_DIR/ros2_ws/src/art_artwork_pipeline"
env -u PYTHONPATH "$A4_LINEART_ENV/bin/python" -m pip check
printf '선화 Python: %s/bin/python\n' "$A4_LINEART_ENV"
