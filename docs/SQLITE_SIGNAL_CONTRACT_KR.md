# JobManager ↔ SQLite 저장소 신호 규격서

이 문서는 `JobManager`와 독립 `SQLite` 저장소 모듈이 서로 연결되기 위해 맞추는 공식 ROS2 신호 규격입니다.

## 1. 연동 원칙

- **역할 분리**
  - `JobManager`는 인메모리 상태에서 작업 접수, 검증, 제어, 상태 전이 판단만 수행합니다.
  - `SQLite` 저장소는 `JobManager`가 내린 결정 이벤트를 수신해 DB에 저장하고, 이력·통계 조회를 담당합니다.
- **단방향 통신**
  - 통신 방향은 `JobManager` → `SQLite` 단방향입니다.
  - `JobManager`는 `SQLite`의 응답을 기다리거나 DB 상태를 직접 조회하지 않으므로, DB 지연이나 오류가 발생해도 로봇 구동 흐름이 멈추지 않습니다.

## 2. ROS2 토픽 및 QoS 규격

- **토픽 이름:** `/art/job_decision`
- **메시지 타입:** `art_interfaces/msg/JobDecision`
- **통신 방식:** ROS2 Topic (Publisher: `job_manager_node` / Subscriber: `sqlite_store_node`)
- **QoS 설정**
  - `Reliability`: `RELIABLE` (결정 이벤트 유실 방지)
  - `Durability`: `VOLATILE`
  - `History`: `KEEP_LAST(100)`

## 3. `JobDecision.msg` 필드 정의

`art_interfaces/msg/JobDecision.msg`에 아래 필드로 정의할 예정입니다.

```text
uint64 seq                 # 단조 증가 시퀀스 번호 (1부터 시작, 재시작 시 초기화 가능)
string event_type          # 결정 이벤트 종류 (4장 목록 참조)
string job_id              # 작업 고유 ID
string state               # 결정 직후 작업 상태
uint32 completed_strokes   # 완료 획 수
uint32 total_strokes       # 전체 획 수
uint32 resume_stroke_id    # 외력 정지·복구 시 재개 기준 획 번호 (해당 없으면 0)
string current_pen         # 현재 펜 (PEN_1 | PEN_2 | PEN_3, 미지정 시 빈 문자열)
string plan_path           # drawing_plan.json 절대 경로
string plan_sha256         # 계획 파일 SHA-256 해시
string command             # 제어 명령 (PAUSE | RESUME | CANCEL | RECOVER, 해당 시)
string request_id          # 중복 클릭 방지용 요청 ID (해당 시)
string error_code          # 오류/거절 코드 (정상 시 빈 문자열)
string message             # 상태 및 결정 설명
float64 occurred_at        # 이벤트 발생 Unix epoch 시각 (초)
```

### 상태(`state`) 값 목록

- `REJECTED`: 작업 등록 거절
- `QUEUED`: 작업 등록 완료 및 실행 대기
- `DISPATCHING`: 실행기(DrawingController)로 실행 요청 전송 중
- `DRAWING`: 실제 로봇 그리기 진행 중
- `PAUSING`: 일시정지 확인 대기 중
- `PAUSED`: 일시정지 완료
- `RESUMING`: 재개 확인 대기 중
- `STOPPING`: 중단 및 안전 복귀 진행 중
- `STOPPED`: 중단 또는 오류로 종료됨 (다음 작업 가능)
- `COMPLETED`: 모든 획 완료
- `RECOVERY_REQUIRED`: 외력·파지 해제·재시작 등으로 물리적 복구 확인 필요

## 4. `event_type` 상세 목록

### 기본 결정 이벤트 (8종)

- **`JOB_REJECTED` (작업 등록 거절 신호)**
  - 발생 시점: `SYSTEM_BUSY`, `INVALID_JOB_ID`, `DUPLICATE_JOB`, `PLAN_*` 검증 오류 등으로 신규 작업을 거절했을 때
  - 주요 필드: `job_id`, `state="REJECTED"`, `error_code`, `message`

- **`JOB_CREATED` (작업 등록 완료 신호)**
  - 발생 시점: `DrawingPlan` 검증을 통과해 작업이 등록되었을 때
  - 주요 필드: `job_id`, `state="QUEUED"`, `total_strokes`, `current_pen`, `plan_path`, `plan_sha256`

- **`JOB_DISPATCHED` (작업 실행 배차 신호)**
  - 발생 시점: 실행기(`/art/execute_drawing`)로 실행 Goal을 전송할 때
  - 주요 필드: `job_id`, `state="DISPATCHING"`, `plan_path`, `plan_sha256`

- **`STATE_CHANGED` (작업 상태 전이 신호)**
  - 발생 시점: 실행 시작(`DISPATCHING` → `DRAWING`), 재개 확인(`RESUMING` → `DRAWING`) 등 일반 상태가 바뀔 때
  - 주요 필드: `job_id`, `state`, `message`

- **`STROKE_COMPLETED` (획 완료 신호)**
  - 발생 시점: 실행기로부터 `STROKE_COMPLETED`를 수신해 완료 획 수가 1 증가했을 때
  - 주요 필드: `job_id`, `state`, `completed_strokes`, `total_strokes`, `current_pen`

- **`CONTROL_REQUESTED` (제어 요청 접수 신호)**
  - 발생 시점: `/art/control_job`으로 `PAUSE`, `RESUME`, `CANCEL`, `RECOVER` 요청이 접수되었을 때
  - 주요 필드: `job_id`, `state`, `command`, `request_id`, `error_code`, `message`

- **`CONTROL_APPLIED` (제어 결과 반영 신호)**
  - 발생 시점: 실행기의 `/art/control_drawing` 응답으로 `PAUSED` 또는 `DRAWING` 상태가 확정되었을 때
  - 주요 필드: `job_id`, `state`, `command`, `error_code`, `message`

- **`JOB_FINISHED` (작업 최종 종료 신호)**
  - 발생 시점: 작업이 `COMPLETED` 또는 `STOPPED`로 최종 마감되었을 때
  - 주요 필드: `job_id`, `state` (`COMPLETED` | `STOPPED`), `completed_strokes`, `total_strokes`, `error_code`, `message`

### 예외 · 외력 감지 · 복구 이벤트 (5종)

- **`EXTERNAL_FORCE_STOP` (외력 감지 즉시 정지 신호)**
  - 발생 시점: 외력 감지로 로봇이 즉시 정지했을 때
  - 주요 필드: `job_id`, `state`, `completed_strokes`, `resume_stroke_id` (재개 기준 획 번호), `error_code="EXTERNAL_FORCE_DETECTED"`, `message` (복귀 지점 정보 포함)

- **`ROBOT_FAULT` (로봇 이상 / 파지 해제 오류 신호)**
  - 발생 시점: 드라이버 오류 또는 그리기 중 펜 파지 해제(`GRIP_LOST`)가 발생했을 때
  - 주요 필드: `job_id`, `state`, `completed_strokes`, `error_code`, `message`

- **`RECOVERY_REQUIRED` (복구 필요 상태 알림 신호)**
  - 발생 시점: 외력 감지, 파지 해제, 재시작 미확인 등으로 물리적 복구가 필요할 때
  - 주요 필드: `job_id`, `state="RECOVERY_REQUIRED"`, `resume_stroke_id`, `error_code`, `message`

- **`RECOVERY_STARTED` (복구 실행 시작 신호)**
  - 발생 시점: `RECOVER` 명령으로 안전 복귀 동작을 시작했을 때
  - 주요 필드: `job_id`, `command="RECOVER"`, `request_id`, `message`

- **`RECOVERY_COMPLETED` (복구 완료 신호)**
  - 발생 시점: 로봇의 안전 복귀 및 펜 원위치가 완료되어 `STOPPED`로 해제되었을 때
  - 주요 필드: `job_id`, `state="STOPPED"`, `command="RECOVER"`, `message`

## 5. SQLite 구현 시 권장 사항

- **테이블 분리 권장**
  - `jobs`: `job_id` 기준 최신 스냅샷 저장 (상태, 완료 획, 전체 획, 계획 경로·SHA, 시작/종료 시각, 마지막 오류)
  - `job_events`: 수신한 모든 `JobDecision`을 시간순(`occurred_at`, `seq`)으로 누적 저장하는 감사/이력 로그
  - `command_receipts`: `CONTROL_REQUESTED` / `CONTROL_APPLIED` 기록 저장 (이력 및 중복 추적용)
- **멱등성 및 순서 처리**
  - `JobManager`가 재시작하면 `seq`는 다시 1부터 시작할 수 있으므로, `job_events`는 `(occurred_at, seq)` 기준으로 기록하고 `jobs` 테이블은 `job_id` 기준으로 Upsert 처리하는 것이 안전합니다.
  - `JOB_REJECTED`는 실제 작업이 생성되지 않았으므로 `job_events`에만 남기거나, 별도 거절 이력으로 처리하는 것을 권장합니다.
