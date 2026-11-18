> ⚠️ **역사적 초안 안내:** 이 문서는 초기 Bridge/구형 JobManager 시점의 인터페이스 설명입니다.
> 최신 통합 사양은 `docs/TEAM_CONTRACT_V1.md`, 최신 코드 흐름은 `docs/TEAM_CODE_FLOW_KR.md`를 우선 참고하세요.
> 최신 기본 실행은 `ros2 run art_job_manager job_manager`, 테스트 실행은 `job_manager_test`입니다.

# JobManager 통합 규약 / 작업 점검

## 연결도

```text
기존 HMI → 기존 FastAPI → KioskBridgeNode
                              ↓ /art/create_job, /art/control_job
                  JobManagerNode → SQLite /data/jobs_demo.db
                              ↓ /art/job_status
                        KioskBridge → HMI 상태 표시

미연결: ArtworkPipeline Action / DrawingController Action / Doosan M0609 / RG2
시뮬레이션: JobManager 내부 timer만 가짜 진행 (실제 구동 명령 없음)
```

## 이번 ZIP이 추가하는 파일

- `ros2_ws/src/art_job_manager/{package.xml,setup.py,setup.cfg,resource/,art_job_manager/}`: 새 ROS 2 패키지.
- `tests/job_manager/`: Python 단위시험 + ROS 실제 통신 시험(환경 없으면 skip).
- `examples/job_manager/`: 검증용 A4 210×297 mm DrawingPlan 및 생성 스크립트.
- `docs/job_manager_integration.md`: 이 문서.

**현재 성공한 KioskBridge 및 art_interfaces 코드는 수정하지 않습니다.**

## 팀원과 파일 맞추기

**`job_manager_node.py`, `job_engine.py`**

- 팀원 파일: `art_kiosk_bridge/bridge_node.py`
- TEAM_SYNC: CreateJob/ControlJob/JobStatus 이름·타입·오류 코드 (현재는 일치)

**`plan.py`**

- 팀원 파일: `ros2_ws/src/art_artwork_pipeline/art_artwork_pipeline/path_planner/cli.py`와 향후 `art_artwork_pipeline`
- TEAM_SYNC: 픽셀 JSON은 입력 불가. A4 mm DrawingPlan 생성 필요

**`job_engine.py:on_controller_*`**

- 팀원 파일: `art_drawing_controller/drawing_node.py`
- TEAM_SYNC: 실제 ROS Action·정지 피드백·pen-up ACK (아직 연결 안 됨)

**`job_repository.py`**

- 팀원 파일: 검증 담당 테스트·운영
- TEAM_SYNC: SQLite 백업·복구·무결성/한 작업 독점 검증

**JobStatus.state**

- 팀원 파일: `ros2_ws/src/art_kiosk/art_kiosk/static/app.js`
- TEAM_SYNC: 상태별 화면·중복 클릭·REcovery UI 승인

## 현재 테스트 증빙 경계

- **코드 작성 환경:** Python 단위시험만 검증. 실제 ROS 2 `rclpy`는 이 환경에 없음.
- **사용자 PC:** 기존 KioskBridge+Mock 9 passed, 1 skipped (이전 대화에서 사용자가 직접 실행).
- **새 JobManager ROS 통신:** 사용자의 Ubuntu 24.04 + Jazzy PC에서 실행해 확인 필요.

## 안전

- 비상정지는 HMI PAUSE/CANCEL과 별도의 물리적 안전 체계여야 함.
- `ART_JOB_SIMULATE=1`은 **시뮬레이션만 수행**, 펜 이격도 가짜 이벤트.
- 기본 모드는 QUEUED 대기만 하므로 그림을 그리지 않음.
- 펜이 종이에 닿은 상태에서 끊긴 획은 `UNCERTAIN`, 재시작 후 자동 반복 금지.
