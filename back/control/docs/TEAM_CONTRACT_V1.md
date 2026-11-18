# A4 팀 통합 기준안 v1 — 검토·수락 요청 (2026-11-16)

**이 문서는 팀의 실제 합의 결과가 아니라, 현재 코드와 맞는 구현 기준안이다.** 변경 요청이 있으면 인터페이스 파일의 새 버전을 합의하고 전원이 같은 Git 커밋으로 빌드한다. Doosan M0609/RG2 실물 안전 인증 또는 실제 주행 검증을 뜻하지 않는다.

## 1. 담당·경계 확정안

**김용수 (통합·시험)**

- 소유 파일·기능: `art_kiosk_bridge`, `art_job_manager` 생산형 Action Client, SQLite, 통합테스트, 인터페이스 문서
- 하지 않는 일: 실제 M0609 모션 명령/비상정지 구현을 대신하지 않음

**장태원 (이미지·백엔드)**

- 소유 파일·기능: `ros2_ws/src/art_kiosk/art_kiosk/server.py`, `art_artwork_pipeline` 경로 생성·px→mm
- 하지 않는 일: JobManager DB 직접 수정하지 않음

**배준영 (PM·UI)**

- 소유 파일·기능: `static/app.js`, 상태/오류/승인 UI, 데모 구성
- 하지 않는 일: HTTP 승인만으로 로봇 `PAUSED` 표시하지 않음

**류민선 (ROS/Robot)**

- 소유 파일·기능: `art_drawing_controller` Action Server, Doosan driver·RG2, 실제 멈춤·펜 이격 피드백
- 하지 않는 일: JobManager `completed_strokes` DB 직접 수정하지 않음

**팀 확인 필수:** JobManager 최종 유지보수 담당, Controller 실물 안전 승인자, 운영 복구 승인자. 본 문서는 제안한 역할 분담이며 팀 수락 전까지 사실로 기록하지 않는다.

## 2. 기존 Web ↔ ROS 계약 (변경하지 않음)

- FastAPI→Bridge (HTTP): `POST http://127.0.0.1:8001/bridge/jobs` 본문 `{"job_id":"JOB_123","plan_path":"/home/USER/A4/data/jobs/JOB_123/drawing_plan.json"}` → 202 Accepted 또는 409/422/503/504.
- 제어: `POST /bridge/jobs/{job_id}/control` 본문 `{"command":"PAUSE|RESUME|CANCEL","request_id":"cmd_001"}`. 같은 `request_id` 재사용은 동일 명령의 재전송만 허용; 다른 명령이면 `REQUEST_ID_CONFLICT`.
- 조회: `GET /bridge/jobs/{job_id}`. Bridge는 `/art/job_status`에서 받은 최신 상태를 캐시한다. 통신 안 됨 = 상태 미확인, 정지 아님.
- ROS 2 Service 이름: `/art/create_job` (`art_interfaces/srv/CreateJob`) / `/art/control_job` (`art_interfaces/srv/ControlJob`). 기존 필드 유지.
- 상태 Topic: `/art/job_status` (`art_interfaces/msg/JobStatus`), 기본 Reliable/Volatile, 1초 주기로 최신 스냅샷 재발행. UI 조회 주기 권장 약 1초.
- Job ID: `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`. 한 작업당 같은 ID 유지, 중복 작업 생성 거절.

## 3. 신규 JobManager → DrawingController Action 계약

**이름:** `/art/execute_drawing` / **타입:** `art_interfaces/action/ExecuteDrawing` (ZIP 동봉). ROS 2 Goal / Result / Feedback의 필드는 아래와 같다.

```text
Goal:
  string job_id               # 공통 작업 ID
  string plan_path            # Controller도 읽을 수 있는 절대 경로
  string plan_sha256          # Controller는 열기 전에 동일 SHA 검증
  uint32 start_stroke_id      # 1부터 시작; PAUSE 후 확인된 마지막 완료 획+1

Result:
  bool success               # 전체 그림이 완료된 경우만 true
  string final_state         # COMPLETED | INTERRUPTED_SAFE | FAILED
  uint32 completed_strokes   # pen-up 확인된 마지막 연속 완료 stroke_id
  bool pen_up_confirmed      # 실제 드라이버가 펜 안전 이격 확인
  string error_code
  string message

Feedback:
  uint32 stroke_id
  string event               # STARTED | HEARTBEAT | STROKE_STARTED | STROKE_COMPLETED
  string pen_id
  bool pen_up_confirmed      # STROKE_COMPLETED에서만 반드시 true
  string message
```

**중요한 취소 규칙:** ROS Action `cancel_goal_async`는 PAUSE와 CANCEL을 구별하지 못한다. Controller는 실제 모션 정지 및 펜 이격 확인 후 **ROS Action CANCELED + `final_state=INTERRUPTED_SAFE` + `pen_up_confirmed=true`** 반환. JobManager가 이미 저장한 명령이 `PAUSING`이면 `PAUSED`, `STOPPING`이면 `STOPPED`로 확정한다. 응답 수신만으로 실제 정지라고 판단하면 안 된다.

**작업 종료:** 모든 획의 `STROKE_STARTED` 및 펜 이격 확인된 `STROKE_COMPLETED`가 순서대로 도착해야 하며, 마지막에 **ROS Action SUCCEEDED + `success=true` + `final_state=COMPLETED` + `pen_up_confirmed=true`**를 받아야 `COMPLETED`로 확정한다.

**Action Server 필수 요구:** 취소 콜백은 실제 정지 처리와 독립적으로 수락하되, Result는 물리적 정지·펜 이격 검증 뒤에만 제출; Driver 미준비/캘리브레이션 불일치 시 Goal 거절; 일정 시간 이상 움직임이 계속되는 동안 `HEARTBEAT` 피드백 발행; Goal의 경로/SHA/시작 획 및 좌표/도구 구성을 재검사; 동일 장비 동시 Goal 금지. ROS Action Server 준비 여부만으로 로봇 안전 상태를 보장하지 않는다.

## 4. ArtworkPipeline → JobManager DrawingPlan v0.1 계약 (기존 파일 호환용)

> **신규 생성 파일은 v0.2 계약을 우선합니다.** `docs/DRAWING_PLAN_V02_KR.md`를 참고하세요. 이 절의 왼쪽 아래 원점은 v0.1 당시 미확정 제안으로, v0.2 종이 좌표계(왼쪽 위 원점)와 다릅니다. 실제 로봇 좌표 변환은 확정 전입니다.

- JobManager에는 픽셀 경로 `*_strokes_px.json`을 전달하지 않는다. 파이프라인이 로봇 작업용 A4 mm DrawingPlan을 생성해야 함.
- 경로: `ART_JOB_PLAN_ROOT/<job_id>/drawing_plan.json` (절대경로, 쓰기 완료 뒤 불변, max 5MB).
- JSON 필수 필드:

```json
{
  "schema_version": "0.1",
  "job_id": "JOB_123",
  "paper_mm": {"width": 210, "height": 297},
  "strokes": [
    {"stroke_id": 1, "pen_id": "PEN_1", "points_mm": [[10, 10], [30, 30]]}
  ]
}
```

- 제안 좌표계: A4 **세로방향**, `paper_a4` 원점은 **왼쪽 아래**, +X 오른쪽, +Y 위쪽, 단위 mm. `0 ≤ X ≤ 210`, `0 ≤ Y ≤ 297`. 픽셀 이미지 원점이 왼쪽 위이므로 Y 반전/크롭 보정이 필요. **이 값은 팀이 수락할 때까지 물리 모션의 보증된 좌표가 아니다.**
- `stroke_id` 1부터 빠짐없이 증가. `pen_id`는 초기 제안 `PEN_1`, `PEN_2`, `PEN_3`; 실제 펜 장착 위치/그리퍼 TCP/펜 압력은 Controller에서 캘리브레이션하고 별도 안전 설정 관리.
- Controller는 paper_a4→robot_base 변환, pen_tip TCP, 작업면 Z, 한계 속도/가속도, 간섭·특이점·작업영역을 실제 장비에서 검증하기 전 **Goal을 거절**해야 한다. JSON의 좌표만으로 안전 구동 가능하다고 보지 않는다.
- 경로 파일은 새 임시 파일에 완성 → 원자적으로 이름 변경하고, SHA-256 값으로 변경 여부 검사. 실행 중 latest 파일 덮어쓰기 금지.

## 5. 상태 / 실패 / 복구 계약

```text
QUEUED → DISPATCHING → DRAWING → COMPLETED
                        │
                        ├─ PAUSE → PAUSING → (Controller safe ack) → PAUSED
                        │                                            └─ RESUME → RESUMING → DRAWING (동일 Action/모션)
                        └─ CANCEL → STOPPING → (Controller safe ack) → STOPPED

재시작 / 통신·Action 결과 불일치 / 안전 미확인 → RECOVERY_REQUIRED (자동 재개 금지)
```

- `PAUSING`/`RESUMING`/`STOPPING`은 확인 대기 상태다. PAUSED는 동일 모션의 실제 정지 확인이며 펜 이격을 뜻하지 않는다. STOPPED는 실제 정지·펜 이격이 확인돼야 한다.
- JobManager는 SQLite에 **확인된 연속 완료 획**과 **진행 중인 불확실 획(uncertain_stroke)**, plan SHA, command_receipts를 저장한다.
- 획 시작은 `uncertain_stroke`에 표시, `STROKE_COMPLETED` + pen-up 확인 시에만 DB 완료 획 증가. 동일 실행의 일시정지 중에는 진행 중 획을 그대로 보존해 이어간다. 실행 문맥을 잃은 중단 획은 자동 재실행하지 않는다.
- Action/통신 실패나 재시작 이후 `RECOVERY_REQUIRED`는 관리자/실물 현황 확인 전 해제 불가. 이 ZIP에는 임의 해제 API를 포함하지 않는다.
- HTTP 오류 예시: `DUPLICATE_JOB`, `SYSTEM_BUSY`, `PLAN_CHANGED`, `INVALID_TRANSITION`, `UNCERTAIN_STROKE`, `UNCONFIRMED_ACTION_RESULT`. 상세한 숫자 HTTP 상태는 Bridge 규약(422/409/503/504) 따름.
- HMI PAUSE는 **물리적 비상정지(E-Stop)를 대체하지 않음**.

## 6. 팀원별 전달·승인 체크

**장태원**

- 함께 전달할 파일: `docs/TEAM_CONTRACT_V1.md`, `art_job_manager/plan.py`, 예제 DrawingPlan
- 꼭 회신받을 내용: px→mm 좌표계·작업별 JSON 원자적 생성·경로 배포 방식

**류민선**

- 함께 전달할 파일: `action/ExecuteDrawing.action`, `job_manager_node.py`, 안전/취소 명세
- 꼭 회신받을 내용: Action 수락/거절, Cancel 안전 확인, stroke feedback, URDF/TF·실물 제어 준비 상태

**배준영**

- 함께 전달할 파일: `CreateJob.srv`, `ControlJob.srv`, `JobStatus.msg`, 상태 전이
- 꼭 회신받을 내용: 작업 ID·request ID·버튼 비활성화·PAUSING/PAUSED 구별·복구 UI

**팀 전원**

- 함께 전달할 파일: 이 계약과 빌드한 Git commit SHA
- 꼭 회신받을 내용: 수락 또는 수정 요청한 필드/타입, 담당자, 서명/리뷰 날짜

**반드시 확인해야 할 미해결 사항:** 물리적 안전 승인·원점 캘리브레이션 값·M0609 드라이버/ROS 패키지 버전·3펜 도구 교체 방식·실물 재시작 후 작업자 승인 절차. 이들은 컴퓨터에서 임의로 확정할 수 없다.

## 추가 안내: 초기 아키텍처와 변경 사항

초기 그림에 없는 `/art/control_job` Service가 v1에 추가되었습니다. 또한 초기 그림의 `/art/execute_job`, `/art/prepare_artwork`, `/art/draw_artwork`, `/art/draw_calligraphy` Action들은 이 ZIP에 구현된 것이 아닙니다. v1의 `/art/execute_drawing` Action은 JobManager→Controller 구간의 **통합 제안안**이며 팀 수락이 필요합니다.

현재 획 중간 정지 계약과 팀원 구현 방법은 [동일 모션 일시정지·재개](CONTINUOUS_PAUSE_RESUME_KR.md)를 따른다.
