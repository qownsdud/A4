# art_kiosk_bridge — KioskBridge

독립 HTTP 서버와 ROS 2 노드를 한 프로세스에서 실행합니다. 기존 키오스크 서버와 별개이며 로봇 드라이버를 직접 호출하지 않습니다.

## 파일과 동작

- **`main.py`**: 환경 변수 검증, Uvicorn과 별도 스레드 SingleThreadedExecutor 기동·종료
- **`http_api.py`**: FastAPI 라우트·HTTP 오류 변환·BridgePort 의존성 주입
- **`schemas.py`**: Pydantic 요청·응답 모델·ID 검증
- **`bridge_node.py`**: KioskBridgeNode, Service 비동기 호출·상태 구독 및 캐시
- **`errors.py`**: 서비스 미연결·시간 초과·응답 불일치 예외

HTTP 핸들러는 `call_async()` 후 20ms 간격으로 완료를 비동기 확인합니다. ROS executor는 별도 스레드에서 Future와 구독 콜백을 처리합니다. 캐시는 lock으로 보호합니다. Uvicorn 다중 worker·reload는 사용하지 않습니다.

## 실행·설정

워크스페이스 빌드 및 setup 적용 후 `ros2 run art_kiosk_bridge bridge`로 실행합니다. 노드 이름은 `kiosk_bridge_node`입니다.

**`ART_BRIDGE_HOST`**

- 기본값: `127.0.0.1`
- 조건: HTTP 바인딩 주소

**`ART_BRIDGE_PORT`**

- 기본값: `8001`
- 조건: 1~65535

**`ART_SERVICE_TIMEOUT_SEC`**

- 기본값: `3.0`
- 조건: 양수

기본 ROS 이름은 `/art/create_job`, `/art/control_job`, `/art/job_status`입니다. 생성자로 변경할 수 있지만 전용 환경 변수는 없습니다.

## HTTP 계약

**`GET /health`**

- 요청: 없음
- 성공 응답: 200, `status`, `job_manager_reachable`

**`POST /bridge/jobs`**

- 요청: `job_id`, `plan_path`
- 성공 응답: 202, 명령 응답

**`POST /bridge/jobs/{job_id}/control`**

- 요청: `command`, `request_id`
- 성공 응답: 202, 명령 응답

**`GET /bridge/jobs/{job_id}`**

- 요청: 없음
- 성공 응답: 200, 마지막 수신 상태

명령 응답 필드: `accepted`, `job_id`, `manager_state`, `error_code`, `message`. ROS의 `state`를 HTTP에서는 `manager_state`로 바꿉니다.

상태 응답 필드: `job_id`, `state`, `completed_strokes`, `total_strokes`, `current_pen`, `error_code`, `message`, `observed_at_unix`.

ID는 1~64자이며 `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`를 따릅니다. `plan_path`는 1~4096자이며 Bridge는 파일을 열지 않고 Manager에 검증을 맡깁니다. 명령은 대문자 `PAUSE`, `RESUME`, `CANCEL`만 허용합니다.

- **404**: 해당 작업 상태를 아직 수신하지 않음
- **409**: Manager의 `accepted=false`, `detail`에 명령 응답 포함
- **422**: 요청·ID·명령 검증 실패
- **502**: ROS 응답이 없거나 응답 job_id 불일치
- **503**: 서비스 미발견 또는 Future 결과의 전송 오류
- **504**: 응답 시간 초과, 실제 작업 상태는 미확정

`/health`는 degraded여도 HTTP 200입니다. 서비스 발견은 로봇 준비 완료를 뜻하지 않습니다.

## 호출 예시

기본 계획 루트에 실제 작업 파일이 준비되어 있다는 가정입니다.

```bash
curl http://127.0.0.1:8001/health
curl -i -X POST http://127.0.0.1:8001/bridge/jobs \
  -H 'Content-Type: application/json' \
  -d "{\"job_id\":\"JOB_001\",\"plan_path\":\"$HOME/A4/data/jobs/JOB_001/drawing_plan.json\"}"
curl http://127.0.0.1:8001/bridge/jobs/JOB_001
curl -i -X POST http://127.0.0.1:8001/bridge/jobs/JOB_001/control \
  -H 'Content-Type: application/json' \
  -d '{"command":"PAUSE","request_id":"pause_001"}'
```

PAUSE는 `DISPATCHING`·`DRAWING`에서만 수락하며 `QUEUED`에서는 거부됩니다. HTTP 202와 `PAUSING`은 실제 정지 완료가 아닙니다. Topic에서 반영된 `PAUSED`를 확인해야 합니다.

시간 초과 시 Future를 취소해도 원격 작업은 취소되지 않습니다. 동일 job_id의 상태를 확인하고 제어 재전송에는 같은 request_id를 유지합니다. 생성 재전송은 `DUPLICATE_JOB`으로 거부될 수 있습니다.

캐시는 메모리에만 있으며 재시작 시 사라집니다. 구독은 depth 10의 기본 reliable/volatile QoS이고 Manager의 매초 재발행으로 다시 채워집니다. 캐시 만료·인증·외부 접근 제어는 구현되어 있지 않습니다.

빌드·테스트는 [워크스페이스 README](../../README.md), ROS 타입은 [인터페이스 README](../art_interfaces/README.md)를 참고하세요.
