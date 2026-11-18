> 최신 상태: 사진→DrawingPlan 연결은 구현되었습니다. 현재 실행 흐름은 [통합 안내](ROS2_PACKAGE_REFACTOR_KR.md)를 참고하세요. 아래는 초기 설계 기록입니다.

# A4 프로젝트: 코드 파일 설명 · 통신 흐름 · 팀 인계 가이드

> 이후 키오스크 사용자 UI(`/`)와 인증키 없는 관리자 HMI(`/admin`)가 분리되었습니다. 현재 FastAPI의 인증·Bridge 중계·준비된 계획 등록·진행률 조회는 [키오스크 README](../ros2_ws/src/art_kiosk/README.md)를 참고하세요. 사진·문구에서 DrawingPlan 자동 생성과 사용자 그리기 승인 후 등록은 현재 구현되어 있습니다. 아래 구형 단계별 설명은 과거 구조를 설명합니다.

## 0. 읽는 순서

1. 이 파일에서 전체 흐름 확인
2. `art_interfaces`의 4개 `.srv/.msg/.action` 계약서 읽기
3. `art_kiosk_bridge/http_api.py` → `bridge_node.py` 읽기
4. `art_job_manager/job_manager_node.py` → `production_engine.py` → `job_repository.py` → `plan.py` 읽기
5. `tests/job_manager_v1/fake_drawing_controller.py`와 각 pytest 테스트 읽기

## 1. 우리가 작성한 코드의 실제 수행 범위

```text
[사용자 사진·문구]  art_kiosk → Bridge → art_artwork_pipeline
     │
     ▼
[이미 존재하는 DrawingPlan JSON]             (사진 → DrawingPlan 실제 자동 생성 연동은 아직 미완료)
     │
     ▼ HTTP: POST /bridge/jobs
[art_kiosk_bridge/http_api.py]              HTTP 유효성 검증/응답
     │
     ▼
[art_kiosk_bridge/bridge_node.py]           ROS 2 CreateJob/ControlJob Service Client
     │
     ▼ /art/create_job, /art/control_job
[art_job_manager/job_manager_node.py]       실제 운영을 목표로 한 ROS Node
     │
     ├─ [plan.py]                           DrawingPlan 스키마·범위·SHA 검증
     ├─ [production_engine.py]              상태 전이·중복 명령·Action 피드백 판단
     └─ [job_repository.py]                 SQLite 저장·재시작 안전 복구
     │
     ├─ /art/job_status Topic ───────────→ [bridge_node.py] → HTTP GET /bridge/jobs/{id}
     │
     ▼ /art/execute_drawing Action (Goal/Feedback/Result)
[DrawingController]                        실제 구현 미연결, 시험용 fake server는 있음
     │
     ▼
[Doosan M0609 / RG2]                      실제 하드웨어 명령/검증 전
```

## 2. '실제 코드'라고 부르는 범위

- `job_manager_node.py`는 Timer로 가짜 그림을 그리지 않습니다. SQLite 작업 생성/복구와 실제 ROS Action Client가 구현되어 있습니다.
- 이 코드 자체가 M0609를 움직이지는 않습니다. Controller Server가 연결되어야 Goal을 처리할 수 있습니다.
- `job_manager_test_node.py`는 예전 시뮬레이션이며, `ART_JOB_SIMULATE=1`일 때만 가상 진행이 일어납니다.
- `tests/job_manager_v1/fake_drawing_controller.py`는 **Action 계약 시험용**이고 실제 로봇 제어가 아닙니다.

## 3. 파일별 책임

**`art_kiosk_bridge/http_api.py`**

- 역할: HTTP /health·작업 생성·제어·조회 API
- 담당/상대: 배준영 UI/기존 FastAPI

**`art_kiosk_bridge/schemas.py`**

- 역할: JSON 필드 유효성 검사
- 담당/상대: 장태원 백엔드/배준영

**`art_kiosk_bridge/bridge_node.py`**

- 역할: HTTP→ROS Service 변환, ROS Topic 상태 수신
- 담당/상대: JobManager

**`art_kiosk_bridge/main.py`**

- 역할: Uvicorn + ROS executor 기동
- 담당/상대: 실행·배포

**`art_kiosk_bridge/errors.py`**

- 역할: HTTP/ROS 통신 오류 분류
- 담당/상대: UI 예외 처리

**`art_interfaces/srv/CreateJob.srv`**

- 역할: 이미 만든 DrawingPlan을 JobManager에 작업으로 등록
- 담당/상대: Bridge ↔ JobManager

**`art_interfaces/srv/ControlJob.srv`**

- 역할: PAUSE/RESUME/CANCEL 명령 전송; **초기 아키텍처 그림에는 없던 v1 추가 규격**
- 담당/상대: Bridge ↔ JobManager

**`art_interfaces/msg/JobStatus.msg`**

- 역할: 확정된 작업 상태·완료 획 통지
- 담당/상대: JobManager → Bridge

**`art_interfaces/action/ExecuteDrawing.action`**

- 역할: 획 실행 Goal·Feedback·Result 계약
- 담당/상대: JobManager ↔ 류민선 Controller

**`art_job_manager/job_manager_node.py`**

- 역할: 실제 Action Client/Service/Topic 연결
- 담당/상대: 사용자 + 류민선

**`art_job_manager/production_engine.py`**

- 역할: QUEUED/PAUSING/PAUSED 등 안전 상태 머신
- 담당/상대: 사용자 + 류민선

**`art_job_manager/job_repository.py`**

- 역할: SQLite 영속 저장소/복구
- 담당/상대: 사용자

**`art_job_manager/plan.py`**

- 역할: DrawingPlan JSON 검증·SHA-256
- 담당/상대: 장태원 Pipeline

**`art_job_manager/job_manager_test_node.py`**

- 역할: **테스트 전용** 시뮬레이션 ROS 노드
- 담당/상대: 사용자 테스트

**`art_job_manager/job_engine.py`**

- 역할: 시뮬레이션 상태 머신
- 담당/상대: 사용자 테스트

**`tests/integration/`**

- 역할: Bridge HTTP/ROS/Mock 계약 검증
- 담당/상대: 사용자 테스트

**`tests/job_manager/`**

- 역할: 구형 JobEngine/Bridge 연결 회귀 테스트
- 담당/상대: 사용자 테스트

**`tests/job_manager_v1/`**

- 역할: 실제 ProductionEngine 안전 테스트와 Fake Controller
- 담당/상대: 사용자 테스트

## 4. ControlJob.srv를 추가한 이유와 원래 아키텍처 차이

원래 아키텍처 그림에는 Bridge→Manager의 `/art/create_job` Service와 `/art/execute_job` Action이 그려졌고, Controller 쪽에 `/art/draw_artwork`, `/art/draw_calligraphy`, Pipeline 쪽 `/art/prepare_artwork`가 있었습니다. 현재 구현에서는 작업 생성과 제어를 **두 개의 Service**(`/art/create_job`, `/art/control_job`)로 구분하고, JobManager→Controller는 **단일** `/art/execute_drawing` Action을 제안했습니다. 이것은 그림과 완전히 같은 인터페이스가 아니므로 `docs/TEAM_CONTRACT_V1.md`를 기준으로 팀원 리뷰를 받아야 합니다.

## 5. 주요 상태와 안전 규칙

- `QUEUED`: 등록 후 Controller 연결/배차 기다림. 로봇 움직임 없음.
- `DISPATCHING`: Action Goal을 보내고 시작 확인 기다림.
- `DRAWING`: Controller가 시작 확인, 획 피드백을 수신 중.
- `PAUSING`: PAUSE 요청이 접수되었지만 물리 정지·펜 이격 미확인.
- `PAUSED`: Controller가 안전한 중단 결과를 보낸 뒤에만 확정.
- `STOPPING`/`STOPPED`: CANCEL에도 동일 규칙.
- `COMPLETED`: 모든 획 완료 + Action SUCCEEDED + pen_up 확인.
- `RECOVERY_REQUIRED`: 통신 장애/불일치/재시작. 자동 재개 금지.
- `request_id`는 명령의 중복 접수를 방지하며, `job_id`는 전 구간 동일 ID.
- E-Stop은 ROS PAUSE/CANCEL과 별개의 실제 하드웨어 안전장치.

## 6. 지금 직접 할 수 있는 테스트

**A — Python 자동시험(실제 모션 없음)**
```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
python3 -m pytest tests/integration tests/job_manager tests/job_manager_v1 -q -rs
```

**B — 브리지/작업 생성(Controller 없음, QUEUED 대기)**
```bash
# 터미널 1: 운영용 JobManager (시뮬레이션 X)
cd ~/A4; source /opt/ros/jazzy/setup.bash; source ros2_ws/install/setup.bash
export ART_JOB_DB="$HOME/A4/data/jobs_real_v1.db"
export ART_JOB_PLAN_ROOT="$HOME/A4/examples/job_manager"
ros2 run art_job_manager job_manager

# 터미널 2: Bridge
cd ~/A4; source /opt/ros/jazzy/setup.bash; source ros2_ws/install/setup.bash
ros2 run art_kiosk_bridge bridge

# 터미널 3: 새 Job ID로 샘플 파일 생성 후 curl 테스트
cd ~/A4
python3 examples/job_manager/create_demo_plan.py JOB_DOC_001 --strokes 30
curl http://127.0.0.1:8001/health
curl -X POST http://127.0.0.1:8001/bridge/jobs -H 'Content-Type: application/json' -d "{"job_id":"JOB_DOC_001","plan_path":"$HOME/A4/examples/job_manager/JOB_DOC_001/drawing_plan.json"}"
curl http://127.0.0.1:8001/bridge/jobs/JOB_DOC_001
```
Controller가 없으면 QUEUED이고 자동 드로잉이 발생하지 않습니다.

**C — 시험용 Fake Controller를 붙여 실제 ROS Action 흐름 확인**
`ROS_DOMAIN_ID=41`을 **JobManager, Bridge, Fake Controller 3개 터미널 모두 동일하게 적용**하고, 실물 로봇/Driver가 없는 환경에서만 Fake Server를 실행하세요. 상세 순서는 아래 3개 터미널 방식입니다.
```bash
# T1 Fake Controller
cd ~/A4; source /opt/ros/jazzy/setup.bash; source ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=41
export A4_ENABLE_FAKE_CONTROLLER=YES
python3 tests/job_manager_v1/fake_drawing_controller.py

# T2 실제 JobManager (테스트 DB 분리)
cd ~/A4; source /opt/ros/jazzy/setup.bash; source ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=41
export ART_JOB_DB="$HOME/A4/data/jobs_fake_action_test.db"
export ART_JOB_PLAN_ROOT="$HOME/A4/examples/job_manager"
ros2 run art_job_manager job_manager

# T3 Bridge
cd ~/A4; source /opt/ros/jazzy/setup.bash; source ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=41
ros2 run art_kiosk_bridge bridge
```
새 터미널 T4에서 위의 curl을 실행하면 Fake Controller의 획 피드백으로 진행률이 바뀝니다. 자세한 PAUSE/RESUME 시험은 `README_REAL_JobManager.md`를 참고하세요. **실제 물리적 로봇 안전 시험은 아님**.

**D — ROS 2 주제·서비스·액션 직접 확인**
```bash
ros2 service list -t | grep /art/
ros2 topic echo /art/job_status
ros2 action list -t
ros2 interface show art_interfaces/srv/ControlJob
ros2 interface show art_interfaces/action/ExecuteDrawing
```

**E — RViz2**
현재 시스템은 RobotModel/TF/JointState 또는 그림 Marker를 발행하지 않습니다. 과거 시험에서 Marker를 직접 발행하면 RViz2에 표시된다는 것만 검증되었습니다. JobManager 획 진행은 터미널/HTTP로 확인 가능하며, 그림/로봇팔 움직임 시각화는 별도 RViz 연동 또는 URDF·Controller 구현이 필요합니다.

## 7. tests/는 실제 실행에 사용하지 않는 파일인가?

아닙니다. 테스트를 **실행할 때 사용**합니다. 평상시 Bridge/JobManager만 실행하면 테스트 파일들은 불리지 않습니다.
- `tests/integration/`: HTTP ↔ ROS/Mock 관련 pytest 테스트
- `tests/job_manager/`: 구형 시뮬레이션 엔진과 ROS 계약의 pytest 테스트
- `tests/job_manager_v1/test_production_engine.py`: 새 운영형 JobManager의 Python 안전 규칙 pytest 테스트
- `tests/job_manager_v1/fake_drawing_controller.py`: pytest 자동 실행 파일이 아니라, 실제 ROS Action 연결을 시험하려면 **수동 실행**하는 별도 Fake Action Server
- `tests/integration/mocks/mock_job_manager.py`: **수동 실행**해 Bridge 단독 시험을 가능하게 하는 Mock Service Server
- `conftest.py`: pytest가 fixture/경로 설정용으로 자동 로드하는 파일

## 8. 팀 통합 전 체크

1. 장태원: 이미 만들어진 plan_path가 실제 ArtworkPipeline 단계에서 언제 완성되는가? A4 mm 좌표계와 SHA 적용은 가능한가?
2. 류민선: `ExecuteDrawing.action` Goal/Feedback/Result 계약, 안전 취소·펜 이격 확인·HEARTBEAT를 구현할 수 있는가?
3. 배준영: 요청 수락과 실제 로봇 안전 상태를 다른 UI 표시로 구현할 수 있는가?
4. 전원: 원본 아키텍처 그림 대비 달라진 Service/Action 이름을 v1로 최종 수락할 것인가?
