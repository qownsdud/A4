# art_interfaces — ROS 2 통신 계약

`ament_cmake`와 `rosidl_generate_interfaces()`로 Python/C++ 타입을 생성합니다. 실행 노드는 없습니다. 현재 규격은 팀 합의가 필요한 초안입니다.

**`/art/create_job`**

- 타입: `art_interfaces/srv/CreateJob`
- 제공·발행: JobManager
- 호출·구독: KioskBridge

**`/art/control_job`**

- 타입: `art_interfaces/srv/ControlJob`
- 제공·발행: JobManager
- 호출·구독: KioskBridge

**`/art/job_status`**

- 타입: `art_interfaces/msg/JobStatus`
- 제공·발행: JobManager
- 호출·구독: KioskBridge

**`/art/execute_drawing`**

- 타입: `art_interfaces/action/ExecuteDrawing`
- 제공·발행: DrawingController
- 호출·구독: JobManager

이름은 인터페이스 파일이 아닌 노드 코드에서 정합니다. 실제 Controller는 별도 구현이 필요합니다. 과거 설계의 `/art/execute_job`, `/art/draw_artwork`, `/art/draw_calligraphy`, `/art/prepare_artwork`는 현재 구현된 이름이 아닙니다.

## Service

**`CreateJob`**

- Request: `string job_id`, `string plan_path`
- Response: `bool accepted`, `string job_id`, `string state`, `string error_code`, `string message`

**`ControlJob`**

- Request: `string job_id`, `string command`, `string request_id`
- Response: CreateJob과 동일

CreateJob은 이미 준비된 DrawingPlan JSON 절대 경로를 전달합니다. `accepted=true`, `QUEUED`는 등록 수락이며 완료가 아닙니다. 동일 ID 생성은 `DUPLICATE_JOB`입니다. 이미지 변환이나 파일 업로드 기능은 없습니다.

ControlJob 명령은 `PAUSE`, `RESUME`, `CANCEL`입니다. `(job_id, request_id)`가 중복 처리 키이며 `PAUSING`·`STOPPING`은 실제 정지 미확정 상태입니다. 허용 전이는 [Manager README](../art_job_manager/README.md)를 참고하세요.

## JobStatus.msg

- **`string job_id`**: 공통 작업 ID
- **`string state`**: QUEUED / DISPATCHING / DRAWING / PAUSING / PAUSED / RESUMING / STOPPING / STOPPED / COMPLETED / RECOVERY_REQUIRED
- **`uint32 completed_strokes`**: 펜 이격까지 확인된 연속 완료 획 수
- **`uint32 total_strokes`**: 전체 획 수
- **`string current_pen`**: 현재 기록된 펜, 등록 시 첫 획의 펜
- **`string error_code`**: 정상 시 빈 문자열
- **`string message`**: 상태 설명

상태는 관측을 반영한 Manager 상태이며 실시간 물리 상태 보장 신호는 아닙니다. 발행·구독은 depth 10의 기본 reliable/volatile QoS입니다. Manager가 약 1초마다 전체 상태를 재발행합니다. 타임스탬프·순번·uncertain_stroke 필드는 없으며 Bridge가 수신 시 `observed_at_unix`를 추가합니다.

## ExecuteDrawing.action

- **Goal**: `string job_id`, `string plan_path`, `string plan_sha256`, `uint32 start_stroke_id`
- **Result**: `bool success`, `string final_state`, `uint32 completed_strokes`, `bool pen_up_confirmed`, `string error_code`, `string message`
- **Feedback**: `uint32 stroke_id`, `string event`, `string pen_id`, `bool pen_up_confirmed`, `string message`

시작 획은 1부터입니다. 동일 실행의 중간 획 RESUME는 새 Goal을 보내지 않습니다. Controller도 같은 경로의 파일을 읽을 수 있어야 하고 SHA를 검증해야 합니다. 분산 머신에서 경로 문자열만 보내는 것으로 파일이 전달되지는 않습니다.

- **`STARTED`**: 구형 실제 실행 시작 반영
- **`STARTED_LIVE`**: 동일 Action·모션을 유지하는 PAUSE/RESUME 지원과 실행 시작 반영
- **`HEARTBEAT`**: 생존 확인만 수행
- **`STROKE_STARTED`**: 다음 획 순서·계획의 펜을 검사해 미확정 획 저장
- **`STROKE_COMPLETED`**: 동일 획 시작 기록·펜 이격 확인 후 체크포인트 확정

미지원 event·순서·펜 불일치는 복구 필요로 처리합니다. Result 완료 획 수만으로 누락된 체크포인트를 보충하지 않습니다.

- **`COMPLETED`**: `SUCCEEDED=4`, success=true, final_state=COMPLETED, 전체 획 확정, 미확정 획 없음, 펜 이격 확인
- **`PAUSED`**: live 실행은 ControlDrawing의 실제 정지 확인으로 확정하며 Action을 종료하지 않습니다. 구형 엔진의 CANCELED/INTERRUPTED_SAFE 검증은 호환용입니다.
- **`STOPPED`**: STOPPING에서 CANCELED=5, success=false, INTERRUPTED_SAFE, 완료 획 일치, 실제 펜 이격 확인

`FAILED` 또는 조건 불일치는 `RECOVERY_REQUIRED`가 됩니다. PAUSE/RESUME는 /art/control_drawing으로 같은 모션을 제어하고 CANCEL만 Action 취소로 전달합니다. Cancel 응답 자체는 실제 정지 확인이 아닙니다.

## 빌드·확인

```bash
cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select art_interfaces art_kiosk_bridge art_job_manager
source install/setup.bash
ros2 interface show art_interfaces/srv/CreateJob
ros2 interface show art_interfaces/srv/ControlJob
ros2 interface show art_interfaces/msg/JobStatus
ros2 interface show art_interfaces/action/ExecuteDrawing
ros2 service list -t
ros2 topic info /art/job_status --verbose
ros2 action list -t
```

필드 변경 시 소비 패키지·별도 Controller를 모두 재빌드하고 실행 터미널마다 최신 overlay를 적용합니다. string인 상태·명령·event는 타입 자체가 열거형으로 제한하지 않으므로 소비 코드 검증도 함께 맞춰야 합니다.

## ControlDrawing.srv

- 요청: job_id, execution_id(Goal UUID hex), command(PAUSE/RESUME), request_id
- 응답: accepted, state(PAUSED/DRAWING/UNKNOWN), error_code, message
- 담당: JobManager → 활성 DrawingController 세션. 새 Goal이나 경로를 만들지 않습니다.

[획 중간 정지와 재개 계약](../../../docs/CONTINUOUS_PAUSE_RESUME_KR.md)
