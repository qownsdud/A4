> **DrawingPlan v0.2:** 새 Phase 3 도안은 `schema_version: "0.2"`이고 종이 왼쪽 위 원점을 `coordinate_frame`으로 명시합니다. 기존 `0.1` 파일은 호환을 위해 계속 읽습니다. [`../../../docs/DRAWING_PLAN_V02_KR.md`](../../../docs/DRAWING_PLAN_V02_KR.md) 참조.

# art_job_manager: 실행용 / 시험용 코드 안내

빌드·전체 구조·검증 명령은 [워크스페이스 README](../../README.md), 통신 필드는 [인터페이스 README](../art_interfaces/README.md)를 참고하세요.

## 운영 노드 환경 변수

- **`ART_JOB_DB`**: `~/A4/data/jobs_real_v1.db`
- **`ART_JOB_PLAN_ROOT`**: `~/A4/data/jobs`
- **`ART_JOB_ACTION_NAME`**: `/art/execute_drawing`
- **`ART_JOB_FEEDBACK_TIMEOUT_SEC`**: `60`, 양수

기본 경로는 현재 디렉토리가 아닌 `Path.home()/A4` 기준입니다. DB 옆 `.lock` 파일에 `fcntl.flock`을 걸어 동일 DB 중복 실행을 막습니다. 다른 DB로 실행한 노드와 ROS 이름이 충돌하는 것은 방지하지 않습니다.

시험 노드의 DB 기본값은 `~/A4/data/jobs.db`입니다. `ART_JOB_SIMULATE=1`, `ART_JOB_SIM_PERIOD=0.25`는 시험 노드에만 적용되며 운영 노드를 시뮬레이션으로 바꾸지 않습니다.

## 작업 생성부터 완료까지

1. CreateJob에서 ID·중복·활성 작업 유무·계획을 검사하고 SQLite에 `QUEUED`로 등록합니다. 대기·일시정지·복구 필요 작업까지 포함하여 한 작업만 허용하므로 여러 작업을 쌓는 큐는 아닙니다.
2. 0.3초 주기 poll에서 Controller를 발견하면 파일과 SHA를 재검증하고 `DISPATCHING`으로 전환합니다. Goal의 시작 획은 마지막 완료 획 + 1입니다.
3. Goal 수락만으로 실행을 확정하지 않습니다. `STARTED` 또는 유효한 획 시작 피드백을 받아 `DRAWING`으로 전환합니다.
4. `STROKE_STARTED`로 미확정 획을 기록하고 같은 획의 `STROKE_COMPLETED`와 `pen_up_confirmed=true`를 받아 완료 획을 확정합니다.
5. 모든 획 체크포인트·펜 이격·Action 성공 결과가 일치해야 `COMPLETED`가 됩니다.

상태 변경 시 발행하며 전체 DB 상태도 약 1초마다 재발행합니다. `HEARTBEAT`는 생존만 확인하고 진행률을 증가시키지 않습니다.

## 상태별 제어

STARTED_LIVE를 보내는 Controller는 획 중간 일시정지를 지원합니다.

- QUEUED에서 CANCEL은 배차 전 STOPPED로 처리합니다.
- DRAWING 또는 DISPATCHING에서 PAUSE는 PAUSING으로 전환하고 동일 실행의 ControlDrawing 서비스를 호출합니다.
  실제 정지 확인 뒤 PAUSED가 됩니다. Action을 취소하거나 진행 중 획을 완료 처리하지 않습니다.
- PAUSED에서 RESUME는 SHA를 다시 검사하고 RESUMING으로 전환합니다.
  같은 Goal UUID와 같은 모션을 재개하며 실제 확인 뒤 DRAWING으로 돌아갑니다.
- PAUSED·RESUMING을 포함한 활성 실행에서 CANCEL은 STOPPING과 Action 취소 요청으로 처리합니다.
  실제 정지·안전 이격과 완료 획 수가 검증된 INTERRUPTED_SAFE 결과 뒤 STOPPED가 됩니다.

진행 중 획은 uncertain_stroke로 남지만 살아 있는 동일 실행이 보존된 경우에만 재개할 수 있습니다.
재시작·통신 불명확·위치 변경 등으로 실행 문맥을 잃으면 RECOVERY_REQUIRED로 보호하고 자동 재개하지 않습니다.
STARTED만 보내는 구형 Controller에 운영 ROS 노드가 보내는 PAUSE는 거절합니다.
구형 상태 엔진의 체크포인트 복구 계약과 테스트는 유지하며 live 모드와 섞지 않습니다.

(job_id, request_id)별 명령 결과를 영속 저장합니다. 같은 요청의 재전송은 모션을 재실행하지 않습니다.
전체 연속 완료 조건이 충족되면 취소와 경합한 작업도 COMPLETED가 될 수 있습니다.

[세부 계약과 로봇 팀 연결 방법](../../../docs/CONTINUOUS_PAUSE_RESUME_KR.md)

## DrawingPlan 입력

```json
{
  "schema_version": "0.1",
  "job_id": "JOB_001",
  "paper_mm": {"width": 210, "height": 297},
  "strokes": [
    {"stroke_id": 1, "pen_id": "PEN_1", "points_mm": [[10, 20], [30, 40]]}
  ]
}
```

- 존재하는 `.json` 절대 경로여야 합니다. resolve한 경로가 계획 루트 내부에 있고 바로 위 디렉토리 이름이 job_id여야 합니다.
- 최대 5,000,000바이트의 UTF-8 JSON, schema `0.1`, 요청과 같은 job_id, 세로 A4 210×297mm를 요구합니다.
- 획은 1~100,000개, stroke_id는 1부터 연속 정수, pen_id는 1~64자 문자열입니다.
- 각 획은 2개 이상의 `[x,y]` 점을 포함합니다. 좌표는 유한한 숫자로 `0≤x≤210`, `0≤y≤297`입니다.
- 원점·축 방향·로봇 프레임 변환·속도·힘·실제 펜 장착 가능 여부는 검증하지 않습니다.

PNG·픽셀 좌표 JSON은 입력 계약을 만족하지 않습니다. 등록된 파일은 변경하지 않아야 하며 Controller도 전달된 SHA를 검증해야 합니다.

## 저장·복구·오류

SQLite는 WAL, `synchronous=FULL`, `BEGIN IMMEDIATE` 트랜잭션을 사용합니다. `jobs`에 상태·SHA·완료 획·미확정 획을, `command_receipts`에 중복 제어 정보를 저장합니다.

운영 엔진은 재시작 시 `QUEUED`, `DISPATCHING`, `DRAWING`, `PAUSING`, `PAUSED`, `STOPPING`, 기존 `RECOVERY_REQUIRED`를 모두 `RECOVERY_REQUIRED`로 기록하고 `UNCONFIRMED_AFTER_RESTART`를 설정합니다. 완료·중단 작업은 유지됩니다. 배차 전 작업도 자동 재실행하지 않습니다.

- **생성 거부**: `INVALID_JOB_ID`, `DUPLICATE_JOB`, `SYSTEM_BUSY`, `PLAN_*`
- **배차 파일 변경·접근 실패**: `PLAN_CHANGED`, `PLAN_UNAVAILABLE`
- **Action 거부·전송·응답·결과 오류**: `ACTION_REJECTED`, `ACTION_SEND_ERROR`, `ACTION_RESPONSE_ERROR`, `ACTION_RESULT_ERROR`
- **잘못된 피드백·결과**: `INVALID_ACTION_FEEDBACK`, `UNCONFIRMED_ACTION_RESULT`
- **피드백 시간 초과**: `CONTROLLER_FEEDBACK_STALE`
- **미확정 획 재개**: `UNCERTAIN_STROKE`

복구 필요 작업은 신규 작업도 막습니다. 현재 복구 승인·작업 조정 API가 없으며 CANCEL로도 해당 상태를 해제할 수 없습니다.

## 시험 범위

`tests/job_manager_v1/test_production_engine.py`는 운영 엔진을 직접 검증합니다. `tests/job_manager_v1/fake_drawing_controller.py`는 수동 실행하는 시험용 Action 서버이며 `A4_ENABLE_FAKE_CONTROLLER=YES`가 필요합니다. Fake·Manager·Bridge에 같은 별도 테스트 ROS_DOMAIN_ID를 적용하고 DB를 분리합니다. 자동 테스트 통과는 운영 노드의 Action 전체 흐름이나 실제 로봇 안전을 검증한 결과가 아닙니다.

> 이 문서는 기존 `A4_JobManager_REAL_v1` 위에 **주석과 파일명 정리**를 적용한 상태를 기준으로 합니다.

**`ros2 run art_job_manager job_manager`**

- Python 진입 모듈: `art_job_manager.job_manager_node:main`
- 용도: **실제 Action Client**: DrawingController가 없으면 대기

**`ros2 run art_job_manager job_manager_test`**

- Python 진입 모듈: `art_job_manager.job_manager_test_node:main`
- 용도: **테스트**: `ART_JOB_SIMULATE=1`일 때 가상 획 증가

- `production_engine.py`: 실제 작업 상태 머신, Controller 피드백을 검증합니다.
- `job_engine.py`: 예전 시뮬레이션 상태 머신, 실제 장비와 연결하지 않습니다.
- `job_repository.py`: 작업별 SQLite 상태·중복 명령·복구 기록을 저장합니다.
- `plan.py`: DrawingPlan JSON 필드·좌표·획 순서를 검사하고 SHA-256을 계산합니다.
- `job_manager_node.py`: `/art/create_job`, `/art/control_job` Service 및 `/art/job_status` Topic, `/art/execute_drawing` Action Client.
- `job_manager_test_node.py`: 테스트용 동일 Service/Topic. **동시에 둘 다 실행 금지**.

## 실제 로봇과 연결하기 전 꼭 확인

현재 Bridge와 JobManager는 이미 생성된 DrawingPlan을 받습니다. 사진을 DrawingPlan으로 만드는 ArtworkPipeline 연결은 아직 구현되지 않았습니다. 실제 로봇을 구동하려면 DrawingController Action Server, M0609/RG2 로봇 드라이버, URDF/좌표 변환, 물리 안전 절차가 추가되어야 합니다.

전체 파일 설명·테스트·실행 방법은 `docs/TEAM_CODE_FLOW_KR.md`를 참조하세요.
