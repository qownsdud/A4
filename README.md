# A4 퍼즐 드로잉 로봇

사진·영문 문구 입력 후 경로를 자동 생성하고 사용자 **그리기** 클릭으로 시작합니다.
관리자는 현재 작업을 자동 조회해 일시정지·재개·중단만 수행합니다.
[참고 코드 통합 결과와 새 선화 환경](docs/REFERENCE_INTEGRATION_KR.md)을 확인하세요.
[최신 HMI 직접 시험 안내](docs/HMI_MANUAL_TEST_KR.md)를 먼저 확인하세요.

Ubuntu 24.04 + ROS2 Jazzy 기반 사진 선화·A4 경로 생성·작업 관리 시스템입니다.
주요 구현은 `ros2_ws/src/`의 기능별 ROS2 패키지로 관리합니다.

- **art_kiosk**: 사용자 사진 입력·선화 확인·관리자 작업 제어
- **art_kiosk_bridge**: HTTP ↔ ROS 서비스·액션 중계
- **art_artwork_pipeline**: CV/DL/MediaPipe 혼합 선화·벡터 경로·A4 mm·퍼즐 색상·영문 필기체
- **art_job_manager**: SQLite·상태 머신·체크포인트·중단과 복구
- **art_drawing_controller**: 확정 계획 실행·펜 교체·실제 관측 기반 제어와 안전 거절
- **art_bringup**: 전체 Launch와 참고 설정
- **art_interfaces**: 메시지·서비스·액션 계약

## 빌드와 실행

```bash
cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
export ART_JOB_PLAN_ROOT="$HOME/A4/data/jobs"
export ART_LINEART_METHOD=cv
ros2 launch art_bringup art_system.launch.py
```

웹은 `http://127.0.0.1:8000`, 관리자 화면은 `/admin`입니다. 관리자 화면은 인증키 없이 열립니다. 기본 접속은 로컬 주소이며 교차 출처 요청은 거절합니다.
경로 자동 생성 → 사용자 미리보기 확인 → 그리기 승인 → 작업 자동 등록 순서입니다.
실물 M0609/RG2와 보정·펜 이격은 미검증이며 실물 검증 프로필을 설정하지 않은 Controller는 물리 실행 Goal을 거절합니다.
제공 인물 사진의 혼합 모델 추론은 확인했습니다. 실물 드로잉과 한글 필기체는 검증·지원 완료로 간주하지 않습니다.

## 테스트

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
source ros2_ws/install/setup.bash
source scripts/local_test_env.bash
PYTHONPATH="/tmp/a4-hmi-js-check:$PYTHONPATH" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ROS_DOMAIN_ID=99 \
  python3 -m pytest -c /dev/null --rootdir=. -o cache_dir=/tmp/a4-pytest-cache tests -q -rs
```

QuickJS가 없으면 프런트엔드 최소 DOM 시험은 건너뜁니다. 테스트 도메인에는 별도 실행 노드를 띄우지 않습니다.

- [통합 결과·의존성·실행·안전 경계](docs/ROS2_PACKAGE_REFACTOR_KR.md)
- [실제 파일 트리](docs/ROS2_REFACTOR_FILE_TREE.txt)
- [키오스크](ros2_ws/src/art_kiosk/README.md)
- [ArtworkPipeline](ros2_ws/src/art_artwork_pipeline/README.md)
- [기존 참고 데이터](data/reference/README.md)

구형 Phase 호환 진입점과 중복 설치 안내는 제거했습니다. 기존 데이터는 `data/reference/`로 이동했고 모든 회귀 시험은 `tests/` 아래에 있습니다.

실물 로봇 담당자는 [실물 로봇 팀 인계 문서](docs/ROBOT_TEAM_HANDOFF_KR.md)에서 현재 구현 범위와 Action 계약을 확인하세요.

[획 중간 일시정지·재개 구현과 팀원 연결 방법](docs/CONTINUOUS_PAUSE_RESUME_KR.md)을 확인하세요.
