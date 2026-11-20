#!/usr/bin/env bash
# A4 Drawing Studio 터미널 서버 가동기 (HTTPS/HTTP 외부 기기 카메라·사진 접속 지원)
set -uo pipefail

A4_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS_DSR_ROOT="${WS_DSR_ROOT:-$HOME/ws_cobot_pjt/ws_dsr}"
LOG_DIR="$A4_ROOT/data/logs"
CERT_DIR="$HOME/.cache/a4/ssl"
mkdir -p "$LOG_DIR" "$CERT_DIR"

SODREAL_LOG="$LOG_DIR/sodreal.log"
SYSTEM_LOG="$LOG_DIR/art_system.log"
TUNNEL_LOG="$LOG_DIR/cloudflared.log"
LOCK_FILE="/tmp/a4_drawing_app.lock"

USE_HTTPS=true
USE_PUBLIC=false
START_ROBOT=true
PORT="${ART_KIOSK_PORT:-8000}"

for arg in "$@"; do
  case "$arg" in
    --no-robot|--ui-only) START_ROBOT=false ;;
    --public) USE_PUBLIC=true ;;
    --http) USE_HTTPS=false ;;
    --https) USE_HTTPS=true ;;
    -h|--help)
      echo "사용법: $0 [--no-robot] [--public] [--http|--https]"
      echo "  (기본값)      두산 로봇 연결 시도 + HTTPS 서버 가동 (같은 네트워크용)"
      echo "  --no-robot    로봇 연결 없이 UI·카메라·선화·경로추출 웹 서버만 즉시 가동"
      echo "  --public      다른 와이파이·LTE/5G에서도 접속 가능한 공인 HTTPS 주소(cloudflared) 생성"
      echo "  --http        HTTPS 대신 일반 HTTP(http://<IP>:$PORT)로 가동"
      exit 0
      ;;
    *)
      echo "[오류] 알 수 없는 옵션: $arg" >&2
      exit 1
      ;;
  esac
done

if [[ "$USE_PUBLIC" == "true" ]]; then
  USE_HTTPS=false
fi

SODREAL_PGID=""
SYSTEM_PGID=""
TUNNEL_PGID=""
CLEANED_UP=false

cleanup() {
  if [[ "$CLEANED_UP" == "true" ]]; then
    return
  fi
  CLEANED_UP=true
  echo -e "\n[A4 Server] 서버 및 관련 프로세스를 종료하고 있습니다..."
  for pgid in "$TUNNEL_PGID" "$SYSTEM_PGID" "$SODREAL_PGID"; do
    if [[ -n "$pgid" ]]; then
      kill -INT -- "-$pgid" 2>/dev/null || true
    fi
  done
  sleep 1.2
  for pgid in "$TUNNEL_PGID" "$SYSTEM_PGID" "$SODREAL_PGID"; do
    if [[ -n "$pgid" ]]; then
      kill -TERM -- "-$pgid" 2>/dev/null || true
    fi
  done
  sleep 0.4
  for pgid in "$TUNNEL_PGID" "$SYSTEM_PGID" "$SODREAL_PGID"; do
    if [[ -n "$pgid" ]]; then
      kill -KILL -- "-$pgid" 2>/dev/null || true
    fi
  done
  flock -u 9 2>/dev/null || true
  exec 9>&- 2>/dev/null || true
  echo "[A4 Server] 종료 완료."
}
trap cleanup EXIT INT TERM

get_host_ips() {
  hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | grep -v '^127\.' | grep -v '^172\.17\.' || true
}

get_primary_ip() {
  local primary
  primary="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')"
  if [[ -z "$primary" ]]; then
    primary="$(get_host_ips | head -n 1)"
  fi
  echo "${primary:-127.0.0.1}"
}

ensure_ssl_cert() {
  local cert="$CERT_DIR/cert.pem"
  local key="$CERT_DIR/key.pem"
  local ips
  ips="$(get_host_ips | tr '\n' ' ')"
  local san="DNS:localhost,IP:127.0.0.1"
  for ip in $ips; do
    san="${san},IP:${ip}"
  done
  local san_file="$CERT_DIR/san.txt"
  if [[ ! -s "$cert" || ! -s "$key" || ! -f "$san_file" || "$(cat "$san_file" 2>/dev/null)" != "$san" ]]; then
    openssl req -x509 -newkey rsa:2048 -nodes \
      -keyout "$key" -out "$cert" -days 3650 \
      -subj "/CN=A4-Drawing-Kiosk" \
      -addext "subjectAltName=${san}" >/dev/null 2>&1
    printf "%s" "$san" > "$san_file"
  fi
  export ART_KIOSK_SSL_CERTFILE="$cert"
  export ART_KIOSK_SSL_KEYFILE="$key"
}

preflight_check() {
  local missing=()
  local dl_py="${ART_DL_PYTHON:-$HOME/.venvs/a4-lineart/bin/python}"
  local face_model="${ART_FACE_MODEL_PATH:-$HOME/.cache/a4/models/face_landmarker.task}"
  [[ -f /opt/ros/jazzy/setup.bash ]] || missing+=("- ROS 2 Jazzy (/opt/ros/jazzy/setup.bash)")
  [[ -f "$A4_ROOT/ros2_ws/install/setup.bash" ]] || missing+=("- ROS 2 빌드 결과 ($A4_ROOT/ros2_ws/install)")
  [[ -x "$dl_py" ]] || missing+=("- AI 선화 가상환경 ($dl_py)")
  [[ -s "$face_model" ]] || missing+=("- MediaPipe 얼굴 모델 ($face_model)")
  if (( ${#missing[@]} > 0 )); then
    echo "[오류] 실행에 필요한 환경이 아직 설치되지 않았습니다:" >&2
    printf '  %s\n' "${missing[@]}" >&2
    echo "먼저 아래 스크립트를 실행해 주세요: $A4_ROOT/scripts/setup_env.bash" >&2
    exit 1
  fi
}

preflight_check

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[오류] A4 서버가 이미 실행 중입니다. 종료하려면 '$A4_ROOT/scripts/stop_a4_app.bash'를 실행하세요." >&2
  exit 1
fi

set +u
source /opt/ros/jazzy/setup.bash
if [[ -f "$WS_DSR_ROOT/install/setup.bash" ]]; then
  source "$WS_DSR_ROOT/install/setup.bash"
else
  source "$A4_ROOT/ros2_ws/install/setup.bash"
fi
set -u

export ART_KIOSK_HOST="${ART_KIOSK_HOST:-0.0.0.0}"
export ART_KIOSK_PORT="$PORT"
export ART_JOB_PLAN_ROOT="${ART_JOB_PLAN_ROOT:-$A4_ROOT/data/jobs}"
export ART_STATE_DB_PATH="${ART_STATE_DB_PATH:-$A4_ROOT/data/art_state.db}"
export ART_LINEART_METHOD="${ART_LINEART_METHOD:-mfl_ld}"
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"

SCHEME="http"
CURL_OPTS="-fsS"
if [[ "$USE_HTTPS" == "true" ]]; then
  ensure_ssl_cert
  SCHEME="https"
  CURL_OPTS="-fsSk"
else
  unset ART_KIOSK_SSL_CERTFILE ART_KIOSK_SSL_KEYFILE
fi

# 1. 로봇 연결 (--no-robot이 아닐 때만 시도하며, 로봇이 꺼져 있어도 웹 UI 서버는 계속 가동)
if [[ "$START_ROBOT" == "true" ]]; then
  echo "[A4 Server] 1/2 두산 로봇(192.168.1.100) 연결 확인 중... (로봇 없이 웹 서버만 바로 띄우려면 --no-robot 옵션 사용)"
  if ping -c 1 -W 1 192.168.1.100 >/dev/null 2>&1; then
    if ! pgrep -f "m0609_rg2_bringup.*bringup\.launch\.py" >/dev/null 2>&1; then
      setsid ros2 launch m0609_rg2_bringup bringup.launch.py \
        mode:=real host:=192.168.1.100 port:=12345 model:=m0609 \
        >"$SODREAL_LOG" 2>&1 < /dev/null 9>&- &
      SODREAL_PGID=$!
    fi
    dsr_ready=false
    for _ in $(seq 1 40); do
      if ros2 service list 2>/dev/null | grep -q "/dsr01/dsr_controller2/system/get_robot_state"; then
        dsr_ready=true
        break
      fi
      sleep 0.5
    done
    if [[ "$dsr_ready" == "true" ]]; then
      echo "[A4 Server] -> 두산 로봇(sodreal) 연결 완료."
    else
      echo "[A4 Server] -> [경고] 두산 로봇 서비스 응답이 없습니다. 웹 UI 및 선화·경로추출 모드로 계속 가동합니다."
    fi
  else
    echo "[A4 Server] -> 현재 로봇(192.168.1.100) 네트워크가 연결되어 있지 않습니다. 웹 UI 및 선화·경로추출 모드로 가동합니다."
  fi
else
  echo "[A4 Server] 1/2 로봇 연결 생략 (--no-robot) -> 웹 UI 및 선화·경로추출 모드로 가동합니다."
fi

# 2. A4 워크스페이스 source 후 art_system 서버 실행
echo "[A4 Server] 2/2 키오스크 웹 서버 및 AI 파이프라인 시작 중..."
set +u
source "$A4_ROOT/ros2_ws/install/setup.bash"
set -u
setsid ros2 launch art_bringup art_system.launch.py \
  >"$SYSTEM_LOG" 2>&1 < /dev/null 9>&- &
SYSTEM_PGID=$!

kiosk_ready=false
for _ in $(seq 1 40); do
  if curl $CURL_OPTS "${SCHEME}://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    kiosk_ready=true
    break
  fi
  sleep 0.5
done

if [[ "$kiosk_ready" != "true" ]]; then
  echo "[오류] 키오스크 서버 시작에 실패했습니다. 로그를 확인해 주세요: $SYSTEM_LOG" >&2
  tail -n 30 "$SYSTEM_LOG" >&2 || true
  exit 1
fi

PRIMARY_IP="$(get_primary_ip)"
PUBLIC_URL=""

if [[ "$USE_PUBLIC" == "true" ]]; then
  CLOUDFLARED_BIN="$(command -v cloudflared || echo "$HOME/.local/bin/cloudflared")"
  if [[ ! -x "$CLOUDFLARED_BIN" ]]; then
    echo "[A4 Server] cloudflared 설치 중..."
    mkdir -p "$HOME/.local/bin"
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" -o "$HOME/.local/bin/cloudflared"
    chmod +x "$HOME/.local/bin/cloudflared"
    CLOUDFLARED_BIN="$HOME/.local/bin/cloudflared"
  fi
  echo "[A4 Server] 외부 접속용 공인 HTTPS 터널 생성 중..."
  : > "$TUNNEL_LOG"
  setsid "$CLOUDFLARED_BIN" tunnel --no-autoupdate --url "http://127.0.0.1:${PORT}" \
    >"$TUNNEL_LOG" 2>&1 < /dev/null 9>&- &
  TUNNEL_PGID=$!
  for _ in $(seq 1 40); do
    PUBLIC_URL="$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -n 1 || true)"
    if [[ -n "$PUBLIC_URL" ]]; then
      break
    fi
    if ! kill -0 "$TUNNEL_PGID" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done
  if [[ -z "$PUBLIC_URL" ]]; then
    echo "[오류] 외부 터널 주소 생성에 실패했습니다. 로그를 확인해 주세요: $TUNNEL_LOG" >&2
    tail -n 20 "$TUNNEL_LOG" >&2 || true
    exit 1
  fi
fi

echo "=================================================================="
echo " A4 Drawing Studio 웹 서버가 가동되었습니다!"
echo "------------------------------------------------------------------"
if [[ -n "$PUBLIC_URL" ]]; then
  echo " [공통 접속 주소 (내 PC · 다른 와이파이 · LTE/5G · 스마트폰 모두 동일)]"
  echo "   - 웹 UI : ${PUBLIC_URL}"
  echo ""
  echo " * 공인 HTTPS 주소가 적용되어 보안 경고 없이 카메라·사진을 바로 사용할 수 있습니다."
else
  echo " [공통 접속 주소 (내 PC · 다른 노트북 · 스마트폰 모두 동일)]"
  echo "   - 웹 UI : ${SCHEME}://${PRIMARY_IP}:${PORT}"
  if [[ "$USE_HTTPS" == "true" ]]; then
    echo ""
    echo " * 참고: 최초 접속 시 브라우저 인증서 안내 화면이 나오면"
    echo "   '고급(세부정보) -> 안전하지 않음으로 이동(웹사이트 방문)'을 한 번 눌러주세요."
    echo "   그러면 접속한 기기의 실시간 카메라와 사진 첨부를 모두 사용할 수 있습니다."
  fi
fi
echo "------------------------------------------------------------------"
echo " * 실시간 로그: $SYSTEM_LOG"
echo " * 서버를 종료하려면 이 터미널에서 Ctrl+C 를 누르세요."
echo "=================================================================="

wait "$SYSTEM_PGID" 2>/dev/null || true
