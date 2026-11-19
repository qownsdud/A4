#!/usr/bin/env bash
# A4 Drawing Studio 원클릭 초기 환경 구축 스크립트 (Ubuntu 24.04 + ROS 2 Jazzy)
# 새 PC에서 브랜치를 받은 뒤 한 번 실행하면 폰트·라이브러리·AI 가상환경·모델·ROS2 빌드·바탕화면 아이콘을 모두 설정합니다.
set -euo pipefail

A4_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ART_DL_VENV:-$HOME/.venvs/a4-lineart}"
MODEL_DIR="${ART_MODEL_DIR:-$HOME/.cache/a4/models}"
FACE_MODEL="$MODEL_DIR/face_landmarker.task"
FACE_MODEL_URL="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
FONT_SRC="$A4_ROOT/assets/fonts/NanumBrush.ttf"
USER_FONT_DIR="$HOME/.local/share/fonts"

SKIP_APT=false
SKIP_DL=false
SKIP_BUILD=false

for arg in "$@"; do
  case "$arg" in
    --skip-apt) SKIP_APT=true ;;
    --skip-dl) SKIP_DL=true ;;
    --skip-build) SKIP_BUILD=true ;;
    -h|--help)
      echo "사용법: $0 [--skip-apt] [--skip-dl] [--skip-build]"
      echo "  --skip-apt    시스템 apt / rosdep 패키지 설치 건너뜀"
      echo "  --skip-dl     a4-lineart Python 가상환경 및 모델 다운로드 건너뜀"
      echo "  --skip-build  ROS 2 colcon build 건너뜀"
      exit 0
      ;;
    *)
      echo "[오류] 알 수 없는 옵션: $arg" >&2
      exit 1
      ;;
  esac
done

log() { echo -e "\n[A4 Setup] $*"; }

log "저장소 경로: $A4_ROOT"

# 1. ROS 2 Jazzy 확인
if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
  echo "[오류] ROS 2 Jazzy(/opt/ros/jazzy/setup.bash)가 설치되어 있지 않습니다." >&2
  echo "먼저 Ubuntu 24.04에 ros-jazzy-desktop을 설치한 뒤 다시 실행해 주세요." >&2
  exit 1
fi

# 2. 시스템 패키지 및 다국어 폰트 설치
if [[ "$SKIP_APT" != "true" ]]; then
  log "1/6 시스템 패키지 및 다국어 폰트 설치 (sudo 권한 필요)"
  sudo apt-get update
  sudo apt-get install -y \
    curl \
    zenity \
    fontconfig \
    libraqm0 \
    python3-venv \
    python3-pip \
    python3-opencv \
    python3-pil \
    python3-numpy \
    python3-scipy \
    python3-fonttools \
    python3-colcon-common-extensions \
    fonts-nanum \
    fonts-noto-cjk \
    fonts-noto-core \
    fonts-dejavu-core
else
  log "1/6 시스템 apt 설치 건너뜀 (--skip-apt)"
fi

# 3. ROS 2 시스템 Python용 웹/키오스크 패키지 확인 및 설치
log "2/6 키오스크/브리지 Python 패키지 확인"
if ! python3 -c "import fastapi, uvicorn, httpx, pydantic, multipart" >/dev/null 2>&1; then
  pip3 install --user --break-system-packages \
    "fastapi>=0.110,<1.0" \
    "uvicorn[standard]>=0.29" \
    "httpx>=0.27" \
    "python-multipart>=0.0.9" \
    "pydantic>=2.0"
else
  echo "  -> 이미 설치되어 있습니다."
fi

# 4. 내장 붓글씨 폰트(NanumBrush.ttf) 사용자 폰트 폴더에도 복사
log "3/6 붓글씨 폰트(NanumBrush.ttf) 등록"
if [[ -f "$FONT_SRC" ]]; then
  mkdir -p "$USER_FONT_DIR"
  cp -f "$FONT_SRC" "$USER_FONT_DIR/NanumBrush.ttf"
  if command -v fc-cache >/dev/null 2>&1; then
    fc-cache -f "$USER_FONT_DIR" || true
  fi
  echo "  -> 등록 완료: $USER_FONT_DIR/NanumBrush.ttf"
else
  echo "  [경고] $FONT_SRC 파일이 없습니다. 시스템 폰트로 대체됩니다."
fi

# 5. MFL-LD 선화용 Python 가상환경 및 얼굴 모델 설치
if [[ "$SKIP_DL" != "true" ]]; then
  log "4/6 AI 선화 가상환경($VENV_DIR) 및 모델 설치"
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    python3 -m venv "$VENV_DIR"
  fi
  "$VENV_DIR/bin/pip" install --upgrade pip
  REQ_LOCK="$A4_ROOT/ros2_ws/src/art_artwork_pipeline/requirements-dl-lock.txt"
  REQ_BASE="$A4_ROOT/ros2_ws/src/art_artwork_pipeline/requirements-dl.txt"
  if [[ -f "$REQ_LOCK" ]]; then
    "$VENV_DIR/bin/pip" install \
      --extra-index-url https://download.pytorch.org/whl/cpu \
      -r "$REQ_LOCK"
  else
    "$VENV_DIR/bin/pip" install \
      --extra-index-url https://download.pytorch.org/whl/cpu \
      -r "$REQ_BASE"
  fi
  "$VENV_DIR/bin/pip" install --no-deps -e "$A4_ROOT/ros2_ws/src/art_artwork_pipeline"

  mkdir -p "$MODEL_DIR"
  if [[ ! -s "$FACE_MODEL" ]]; then
    echo "  -> MediaPipe 얼굴 모델 다운로드 중..."
    curl -fsSL "$FACE_MODEL_URL" -o "$FACE_MODEL.tmp"
    mv -f "$FACE_MODEL.tmp" "$FACE_MODEL"
  fi
  echo "  -> 얼굴 모델 준비 완료: $FACE_MODEL"
else
  log "4/6 AI 선화 가상환경/모델 설치 건너뜀 (--skip-dl)"
fi

# 6. ROS 2 워크스페이스 빌드 (두산 드라이버 포함)
if [[ "$SKIP_BUILD" != "true" ]]; then
  log "5/6 ROS 2 워크스페이스 빌드 ($A4_ROOT/ros2_ws)"
  set +u
  source /opt/ros/jazzy/setup.bash
  set -u
  if [[ "$SKIP_APT" != "true" ]] && command -v rosdep >/dev/null 2>&1; then
    rosdep install --from-paths "$A4_ROOT/ros2_ws/src" --ignore-src -r -y || true
  fi
  (cd "$A4_ROOT/ros2_ws" && colcon build)
else
  log "5/6 ROS 2 빌드 건너뜀 (--skip-build)"
fi

# 7. 현재 PC 경로 기준 바탕화면 및 앱 메뉴 런처 생성
log "6/6 바탕화면 실행 아이콘 등록"
chmod +x "$A4_ROOT/scripts/launch_a4_app.bash" "$A4_ROOT/scripts/stop_a4_app.bash" "$A4_ROOT/scripts/setup_env.bash" 2>/dev/null || true

DESKTOP_ENTRY="[Desktop Entry]
Version=1.0
Type=Application
Name=A4 Drawing Studio
Comment=두산 로봇 A4 퍼즐 드로잉 키오스크 실행
Exec=$A4_ROOT/scripts/launch_a4_app.bash
Icon=$A4_ROOT/scripts/a4_app_icon.svg
Terminal=false
Categories=Utility;Graphics;
StartupWMClass=A4DrawingStudio
"

mkdir -p "$HOME/.local/share/applications"
printf "%s" "$DESKTOP_ENTRY" > "$HOME/.local/share/applications/a4-drawing.desktop"
chmod +x "$HOME/.local/share/applications/a4-drawing.desktop"

if [[ -d "$HOME/Desktop" ]]; then
  printf "%s" "$DESKTOP_ENTRY" > "$HOME/Desktop/A4_Drawing.desktop"
  chmod +x "$HOME/Desktop/A4_Drawing.desktop"
  if command -v gio >/dev/null 2>&1; then
    gio set "$HOME/Desktop/A4_Drawing.desktop" metadata::trusted true 2>/dev/null || true
  fi
fi

# 최종 자체 점검
log "환경 자체 점검 실행 중..."
set +u
source /opt/ros/jazzy/setup.bash
if [[ -f "$A4_ROOT/ros2_ws/install/setup.bash" ]]; then
  source "$A4_ROOT/ros2_ws/install/setup.bash"
fi
set -u

python3 - <<'EOF'
import cv2, fastapi, uvicorn, httpx, pydantic, fontTools
from PIL import features
assert hasattr(cv2, "ximgproc"), "opencv-contrib(ximgproc)가 필요합니다."
print("  [OK] 시스템 Python 패키지 / OpenCV ximgproc / HarfBuzz raqm:", features.check("raqm"))
EOF

if [[ -x "$VENV_DIR/bin/python" ]]; then
  "$VENV_DIR/bin/python" -c "import torch, controlnet_aux, mediapipe, art_artwork_pipeline; print('  [OK] a4-lineart DL 가상환경 정상')"
fi
if [[ -s "$FACE_MODEL" ]]; then
  echo "  [OK] 얼굴 랜드마크 모델 정상 ($FACE_MODEL)"
fi
if [[ -f "$FONT_SRC" ]]; then
  echo "  [OK] 붓글씨 내장 폰트 정상 ($FONT_SRC)"
fi
if ! command -v google-chrome >/dev/null 2>&1 && ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1; then
  echo "  [안내] Google Chrome 또는 Chromium이 설치되어 있지 않습니다. 앱 창 실행을 위해 Chrome 설치를 권장합니다."
fi

echo -e "\n[완료] 모든 준비가 끝났습니다. 바탕화면의 'A4 Drawing Studio' 아이콘을 더블클릭해 실행하세요."
