# `back/` 보관 디렉터리 안내

이 디렉터리는 현재 `art_system.launch.py` 기반 드로잉 시스템에서 직접 사용하지 않는 이전 제어 계층(`JobManager`, `DrawingController`), 통합 테스트, 참고 자료, 작업 백업을 보관하는 곳입니다.

## 현재 활성 시스템 (`ros2_ws/src/`)

현재 실제로 실행되는 패키지는 다음 5개입니다.

- `art_kiosk`: 웹 키오스크 UI 및 프론트엔드 서버
- `art_kiosk_bridge`: HTTP 요청과 ROS2 인터페이스 중계
- `art_artwork_pipeline`: 사진 → 선화 → `DrawingPlan` 생성 (`artwork_pipeline`) 및 `draw_image_standalone.py` 실행 래퍼 (`standalone_drawer`)
- `art_interfaces`: ROS2 메시지/서비스/액션 정의 (`PrepareArtwork`, `CreateJob`, `ControlJob`, `JobStatus` 등)
- `art_bringup`: `art_system.launch.py` 실행 구성

## `back/` 하위 디렉터리 구성

### `back/control/` (이전 중앙 제어 및 로봇 제어기 계층)

현재 `standalone_drawer`로 대체되어 실행되지 않는 `art_job_manager`(SQLite 포함)와 `art_drawing_controller` 관련 자산입니다. 추후 `JobManager`와 `SQLite`를 분리·재구축할 때 참고용으로 사용합니다.

- `back/control/ros2_ws/src/art_job_manager/`: 기존 `JobManager` 노드(`job_manager_node.py`), 상태 머신(`production_engine.py`), SQLite 저장소(`job_repository.py`), 계획 검증(`plan.py`)
- `back/control/ros2_ws/src/art_drawing_controller/`: 기존 `DrawingController` 노드(`drawing_node.py`), 두산 어댑터(`doosan_adapter.py`), 획 실행기(`stroke_executor.py`), 9점·기준막대 캘리브레이션(`calibration_probe.py`)
- `back/control/tests/`: `job_manager`, `job_manager_v1`, `drawing_controller`, `integration` 구 테스트 및 `mocks/checkpoint_stub.py`
- `back/control/docs/`: 구 5노드 아키텍처·계약·리팩토링·연동 문서 (`REFERENCE_INTEGRATION_KR.md`, `TEAM_CONTRACT_V1.md`, `TEAM_CODE_FLOW_KR.md`, `integration_contract.md`, `CONTINUOUS_PAUSE_RESUME_KR.md`, `job_manager_integration.md`, `ROBOT_TEAM_HANDOFF_KR.md`, `TEAM_MESSAGE_TO_SEND.md`, `ROS2_PACKAGE_REFACTOR_KR.md`, `ROS2_REFACTOR_FILE_TREE.txt`)
- `back/control/scripts/`: 로컬 Fake 시험용 환경 스크립트 (`local_test_env.bash`)
- `back/control/examples/`, `README_REAL_JobManager.md`, `README_JobManager_ADDON.md`: `JobManager` 예제 및 안내서

### `back/specification/`

초기 AI 선화 생성, 벡터 경로 추출, ROS2 하드웨어 통합 명세 텍스트입니다.

### `back/reference/`

초기 참고용 선화(`lineart/`), 키오스크(`kiosk/`), 경로 계획(`path_planner/`) 샘플 및 출력물입니다.

### `back/data/`

이전 테스트 및 실행 시 생성된 작업 디렉터리(`jobs/`) 백업입니다.
