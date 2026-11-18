> ⚠️ **역사적 초안 안내:** 이 문서는 초기 Bridge/구형 JobManager 시점의 인터페이스 설명입니다.
> 최신 통합 사양은 `docs/TEAM_CONTRACT_V1.md`, 최신 코드 흐름은 `docs/TEAM_CODE_FLOW_KR.md`를 우선 참고하세요.
> 최신 기본 실행은 `ros2 run art_job_manager job_manager`, 테스트 실행은 `job_manager_test`입니다.

# A4 통합 인터페이스 계약 — 팀 협의 초안

## 현재 흐름
`ros2_ws/src/art_kiosk/art_kiosk/static/app.js` → `ros2_ws/src/art_kiosk/art_kiosk/server.py` → HTTP → `art_kiosk_bridge/http_api.py` → `bridge_node.py` → `JobManagerNode` → Pipeline/Controller → Doosan M0609/RG2.

> 기존 FastAPI에는 Bridge 제어 API가 구현되어 있지 않습니다. 장태원이 기존 코드를 연동하기 전까지 Bridge는 curl 및 Mock으로만 시험합니다.

## 파일-파일 인계 표

**배준영**

- 상대 파일: `ros2_ws/src/art_kiosk/art_kiosk/static/app.js`
- 내 파일: `http_api.py`, `schemas.py`
- 정해야 할 것: HMI 버튼명, 응답 화면, PAUSING/PAUSED 구분

**장태원**

- 상대 파일: `ros2_ws/src/art_kiosk/art_kiosk/server.py`
- 내 파일: `http_api.py`, `schemas.py`
- 정해야 할 것: HTTP URL/port, 작업 ID, 타임아웃, 예외 응답

**장태원**

- 상대 파일: `ros2_ws/src/art_artwork_pipeline/art_artwork_pipeline/path_planner/cli.py`
- 내 파일: `test_e2e_mock.py`
- 정해야 할 것: 픽셀 JSON vs 로봇 mm 계획 구분

**파이프라인 담당**

- 상대 파일: `art_artwork_pipeline/pipeline_node.py`
- 내 파일: `test_e2e_mock.py`
- 정해야 할 것: DrawingPlan JSON 파일 경로/버전/펜 좌표

**JobManager 담당(미확정)**

- 상대 파일: `art_job_manager/job_manager_node.py`
- 내 파일: `bridge_node.py`
- 정해야 할 것: CreateJob/ControlJob 타입/에러/상태

**JobManager 담당(미확정)**

- 상대 파일: `job_repository.py`
- 내 파일: `test_checkpoint_recovery.py`
- 정해야 할 것: 완료 획 확정·부분 획 복구 방식

**류민선**

- 상대 파일: `art_drawing_controller/drawing_node.py`
- 내 파일: `test_bridge_ros.py`, `test_e2e_mock.py`
- 정해야 할 것: Action 상태·정지 완료 신호·펜 이격 확인

**팀 공통**

- 상대 파일: `art_interfaces/{srv,msg}`
- 내 파일: `bridge_node.py`, `mock_job_manager.py`
- 정해야 할 것: 실제 ROS 2 타입과 QoS 최종 승인

## 현재 제안 HTTP API (Bridge side only)
- `POST /bridge/jobs`: `{"job_id":"JOB_001","plan_path":"/abs/path/drawing_plan.json"}` → 202 accepted + manager_state. **plan_path 입력 유효성/접근 권한은 실제 JobManager가 검증해야 합니다.**
- `POST /bridge/jobs/JOB_001/control`: `{"command":"PAUSE|RESUME|CANCEL","request_id":"P1"}` → 202 accepted + manager_state.
- `GET /bridge/jobs/JOB_001`: JobStatus Topic에서 마지막 수신한 상태. 수신하지 못했다면 404, 오래된 상태일 경우 별도 TTL 합의 필요.
- `GET /health`: ROS Service 존재 여부 (로봇 가동 준비 상태와 구분).
- 실패: 잘못된 입력 422, 명령 거부/중복 작업 409, Service 부재 503, ROS 응답 시간초과 504, 타입 불일치 502.

## 제안 ROS 인터페이스
- `/art/create_job` (`art_interfaces/srv/CreateJob`): `job_id`, `plan_path` → `accepted`, `job_id`, `state`, `error_code`, `message`.
- `/art/control_job` (`ControlJob`): `job_id`, `command`, `request_id` → 위 응답.
- `/art/job_status` (`art_interfaces/msg/JobStatus`): `job_id`, `state`, `completed_strokes`, `total_strokes`, `current_pen`, `error_code`, `message`.
- 실제 Action `PrepareArtwork`/`ExecuteDrawing` 인터페이스는 **파이프라인·로봇 담당자가 설계할 항목**으로 이 코드에서 만들어진 척하지 않습니다.

## 안전한 상태 정책
- HTTP PAUSE accepted, JobManager `PAUSING`, Driver 실제 정지 확인 후 JobManager `PAUSED`는 서로 다릅니다.
- Timeout/연결 단절은 작업 실패/정지 확정이 아니라 **상태 미확정**입니다. 재조회 후 운영자 판단 필요.
- <b>Mock의 PAUSED는 실제 로봇 안전성을 증명하지 못합니다.</b>
- 중복 요청 `request_id`는 Mock이 메모리에서만 제거합니다. 실물 시스템의 영속 멱등성·복구 정책은 JobManager 담당과 합의해야 합니다.
- 실제 Driver가 완료하고 펜을 올렸다고 확인한 획만 SQLite 완료 체크포인트로 확정합니다.

## TEAM_SYNC 체크리스트
- [ ] FastAPI에 추가할 `/api/jobs` 계열 실제 라우트·Bridge URL·인증/접근 제어 결정
- [ ] ROS 서비스/토픽 이름, `.srv`/`.msg` 필드 타입, 누가 `job_id` 생성하는지 합의
- [ ] ROS service 장애 시 retry 정책(동일 request_id 유지/중복 실행 금지)
- [ ] `JobStatus` QoS, 상태 stale timeout, 재연결 시 상태 재조회 API 결정
- [ ] `DrawingPlan` 경로 보안, schema_version·mm 좌표 원점·pen_id 합의
- [ ] Driver `PAUSE`/`CANCEL` 실제 정지 감지 및 PAUSED 발행 조건 확인
- [ ] JobManager 구현 담당/SQLite 스키마/DB 백업·복구 검증 확정
- [ ] 운영 PC/서비스 포트·방화벽·실물 시험 안전 승인

## 버전 기록

**2026-11-16**

- 버전: 0.1-DRAFT
- 변경 내용: 독립 HTTP Bridge와 Mock용 초기 계약
- 승인: 팀 검토 전
