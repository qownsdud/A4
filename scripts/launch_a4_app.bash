#!/usr/bin/env bash
# A4 Drawing Studio 통합 실행기 (sodreal -> art_system -> 독립 앱 창 -> 종료 시 자동 정리)
set -uo pipefail

A4_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS_DSR_ROOT="${WS_DSR_ROOT:-$HOME/ws_cobot_pjt/ws_dsr}"
LOG_DIR="$A4_ROOT/data/logs"
mkdir -p "$LOG_DIR"

SODREAL_LOG="$LOG_DIR/sodreal.log"
SYSTEM_LOG="$LOG_DIR/art_system.log"
CHROME_PROFILE="$HOME/.cache/a4-kiosk-chrome"
LOCK_FILE="/tmp/a4_drawing_app.lock"

SODREAL_PGID=""
SYSTEM_PGID=""
PROGRESS_PID=""

show_error() {
  local msg="$1"
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title="A4 Drawing Studio" --text="$msg" --width=420 2>/dev/null || true
  elif command -v notify-send >/dev/null 2>&1; then
    notify-send "A4 Drawing Studio 오류" "$msg" || true
  fi
}

cleanup() {
  if [[ -n "$PROGRESS_PID" ]] && kill -0 "$PROGRESS_PID" 2>/dev/null; then
    kill "$PROGRESS_PID" 2>/dev/null || true
  fi
  for pgid in "$SYSTEM_PGID" "$SODREAL_PGID"; do
    if [[ -n "$pgid" ]]; then
      kill -INT -- "-$pgid" 2>/dev/null || true
    fi
  done
  sleep 1.5
  for pgid in "$SYSTEM_PGID" "$SODREAL_PGID"; do
    if [[ -n "$pgid" ]]; then
      kill -TERM -- "-$pgid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

open_app_window() {
  local url="http://127.0.0.1:8000"
  if command -v google-chrome >/dev/null 2>&1; then
    google-chrome --app="$url" --user-data-dir="$CHROME_PROFILE" --class="A4DrawingStudio" --start-maximized
  elif command -v chromium >/dev/null 2>&1; then
    chromium --app="$url" --user-data-dir="$CHROME_PROFILE" --class="A4DrawingStudio" --start-maximized
  elif command -v chromium-browser >/dev/null 2>&1; then
    chromium-browser --app="$url" --user-data-dir="$CHROME_PROFILE" --class="A4DrawingStudio" --start-maximized
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url"
    echo "Chrome/Chromium이 없어 기본 브라우저로 열었습니다. 종료하려면 Ctrl+C를 누르세요."
    wait "$SYSTEM_PGID" 2>/dev/null || sleep infinity
  else
    show_error "실행할 브라우저(Google Chrome 또는 Chromium)를 찾을 수 없습니다."
    exit 1
  fi
}

# 실행 전 필수 환경 점검 (새 PC에서 setup_env.bash 미실행 시 안내)
preflight_check() {
  local missing=()
  local dl_py="${ART_DL_PYTHON:-$HOME/.venvs/a4-lineart/bin/python}"
  local face_model="${ART_FACE_MODEL_PATH:-$HOME/.cache/a4/models/face_landmarker.task}"
  [[ -f /opt/ros/jazzy/setup.bash ]] || missing+=("- ROS 2 Jazzy (/opt/ros/jazzy/setup.bash)")
  [[ -f "$A4_ROOT/ros2_ws/install/setup.bash" ]] || missing+=("- ROS 2 빌드 결과 ($A4_ROOT/ros2_ws/install)")
  [[ -x "$dl_py" ]] || missing+=("- AI 선화 가상환경 ($dl_py)")
  [[ -s "$face_model" ]] || missing+=("- MediaPipe 얼굴 모델 ($face_model)")
  if (( ${#missing[@]} > 0 )); then
    local joined
    joined="$(printf '%s\n' "${missing[@]}")"
    show_error "실행에 필요한 환경이 아직 설치되지 않았습니다:\n\n${joined}\n\n터미널에서 아래 명령어를 한 번 실행해 주세요:\n$A4_ROOT/scripts/setup_env.bash"
    exit 1
  fi
}

# 이미 8000 포트가 열려 있으면 새 앱 창만 바로 엽니다.
if curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
  open_app_window
  exit 0
fi

preflight_check

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  show_error "A4 Drawing Studio가 이미 시작 중입니다. 잠시만 기다려 주세요."
  exit 1
fi

set +u
source /opt/ros/jazzy/setup.bash
if [[ -f "$WS_DSR_ROOT/install/setup.bash" ]]; then
  source "$WS_DSR_ROOT/install/setup.bash"
else
  # 새 PC에 별도 ws_dsr이 없으면 저장소에 내장된 vendor 두산 드라이버를 사용합니다.
  source "$A4_ROOT/ros2_ws/install/setup.bash"
fi
set -u

export ART_JOB_PLAN_ROOT="${ART_JOB_PLAN_ROOT:-$A4_ROOT/data/jobs}"
export ART_STATE_DB_PATH="${ART_STATE_DB_PATH:-$A4_ROOT/data/art_state.db}"
export ART_LINEART_METHOD="${ART_LINEART_METHOD:-mfl_ld}"
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"

# 진행률 안내창 시작
if command -v zenity >/dev/null 2>&1; then
  (
    echo "# 1/3 두산 로봇(sodreal) 연결 중..."
    while sleep 0.5; do echo "#"; done
  ) | zenity --progress --title="A4 Drawing Studio" --text="1/3 두산 로봇(sodreal) 연결 중..." --pulsate --no-cancel --auto-close --width=360 2>/dev/null &
  PROGRESS_PID=$!
fi

# 1. sodreal 실행 (ws_dsr 환경만으로 실행해 m0609_rg2_bringup 경로 충돌 방지)
if ! pgrep -f "m0609_rg2_bringup.*bringup\.launch\.py" >/dev/null 2>&1; then
  setsid ros2 launch m0609_rg2_bringup bringup.launch.py \
    mode:=real host:=192.168.1.100 port:=12345 model:=m0609 \
    >"$SODREAL_LOG" 2>&1 < /dev/null &
  SODREAL_PGID=$!
fi

# /dsr01/dsr_controller2 서비스 대기 (최대 25초)
dsr_ready=false
for _ in $(seq 1 50); do
  if ros2 service list 2>/dev/null | grep -q "/dsr01/dsr_controller2/system/get_robot_state"; then
    dsr_ready=true
    break
  fi
  if [[ -n "$SODREAL_PGID" ]] && ! kill -0 "$SODREAL_PGID" 2>/dev/null; then
    break
  fi
  sleep 0.5
done

if [[ "$dsr_ready" != "true" ]]; then
  show_error "로봇(sodreal) 연결에 실패했습니다.\n로봇 전원 및 랜선(192.168.1.100)을 확인한 뒤 다시 실행해 주세요.\n\n로그: $SODREAL_LOG"
  exit 1
fi

# 2. A4 워크스페이스 source 후 art_system 서버 실행
set +u
source "$A4_ROOT/ros2_ws/install/setup.bash"
set -u
setsid ros2 launch art_bringup art_system.launch.py \
  >"$SYSTEM_LOG" 2>&1 < /dev/null &
SYSTEM_PGID=$!

kiosk_ready=false
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
    kiosk_ready=true
    break
  fi
  sleep 0.5
done

if [[ -n "$PROGRESS_PID" ]] && kill -0 "$PROGRESS_PID" 2>/dev/null; then
  kill "$PROGRESS_PID" 2>/dev/null || true
  PROGRESS_PID=""
fi

if [[ "$kiosk_ready" != "true" ]]; then
  show_error "키오스크 서버 시작에 실패했습니다.\n로그를 확인해 주세요: $SYSTEM_LOG"
  exit 1
fi

# 3. 전용 앱 창 실행 (창을 닫으면 trap cleanup이 서버와 로봇을 자동 종료)
open_app_window
