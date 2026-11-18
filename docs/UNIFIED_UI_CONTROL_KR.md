> 아래는 이전 버전의 기록입니다. 현재 버튼·SQLite·재개 정책은 [중단점 복구와 새 그림 시작](CHECKPOINT_RECOVERY_KR.md)을 우선 적용하세요. 초기화·외력 후 처음부터 그리기와 수동 허용 체크박스는 현재 사용하지 않습니다.

# 통합 UI와 실시간 드로잉 제어

보정 파일 복사와 제어기 보호 모드 추가 이후의 최신 절차는 [실물 실행 준비 안내](REAL_ROBOT_NEXT_STEPS_KR.md)를 먼저 따르세요. 아래 외력 임계값 설명은 추가 소프트웨어 감시 모드에 해당합니다.

## 현재 구성

현재 로컬 저장소는 JobManager와 SQLite 없이 동작한다. 실행 상태와 명령 중복 방지는 메모리에 보관하고 사진·선화·DrawingPlan은 `ART_JOB_PLAN_ROOT/<job_id>/`에 저장한다. 프로세스 재시작 후 자동으로 이어 그리는 기능은 제공하지 않는다. 상태를 확인할 수 없으면 새 그림을 시작하지 않는다.

실행 흐름은 UI → Kiosk HTTP → Bridge → `/art/create_job`, `/art/control_job` 서비스 → ArtworkPipeline의 `standalone_drawer` → 제공된 `draw_image_standalone.py` → Doosan 드라이버이다. `/art/job_status` 토픽으로 실제 관측 상태와 길이 진행률을 UI에 전달한다. 선화와 계획 생성은 `/art/prepare_artwork` 액션을 사용한다.

관리자 기능은 사용자 화면으로 합쳤다. `/admin`은 `/`로 이동한다. 사진·영문 문구를 입력하면 경로를 생성하고, 사용자가 **그리기**를 누르면 실행한다. 한 번에 하나의 작업만 허용한다.

## 버튼의 의미

- **일시정지**: 현재 이동을 정지시키고 실제 TCP 위치를 확인한다. 펜을 들어 올린 뒤 기존 홈 자세로 이동한다. 홈 도착 확인 후 `PAUSED`(일시정지 완료)를 표시한다.
- **재개**: 홈 관절 자세가 임의로 변경되지 않았는지 확인한다. 저장한 펜 상승 자세와 중단 위치로 돌아간 뒤 그 선분의 남은 목표점부터 계속 그린다. 선분 밖으로 벗어난 위치는 자동 재개하지 않는다.
- **초기화**: 진행 중 이동을 정지하고 펜을 안전 높이로 이동·반납한 뒤 홈으로 돌아간다. 같은 계획을 처음부터 즉시 다시 그리며 진행률과 실행 회차를 초기화한다. 새 종이 준비는 버튼을 누르기 전에 마친다.

명령 수신 응답만으로 정지·홈 도착을 완료 처리하지 않는다. 이동 관측 실패나 통신 단절은 `RECOVERY_REQUIRED`(현장 상태 확인 필요)로 처리한다. UI에 표시되는 진행률은 전체 계획의 펜이 내려간 선 길이에 대한 완료 길이 비율이며, 긴 획의 이동 중에도 실제 TCP 위치로 갱신한다. 홈 이동·펜 교체·펜 상승 거리는 제외한다.

## 외력 또는 보호 정지

기존 압력 측정·기준면 측정 코드는 유지했다. 드로잉 단계의 외력 감시는 별도 설정의 6축 측정값과 정상 오프셋을 비교하며, 드라이버의 보호 정지 상태도 감시한다. 외력 정지에서는 임의로 홈 이동하거나 서보를 켜지 않는다.

UI는 `FORCE_STOPPED`(외력·보호 정지)를 표시하고 **초기화만** 허용한다. 작업자가 원인을 제거하고 로봇을 정상 대기 상태로 복구한 뒤 초기화를 누른다. 외력이 남아 있거나 정상 상태가 아니면 초기화를 거절한다. 초기화가 성공하면 처음부터 그린다.

이 소프트웨어 감시는 안전 등급이 있는 장치가 아니다. 로봇의 충돌 감지와 물리 비상정지를 대체하지 않는다. 정지 서비스의 응답만으로 정지했다고 간주하지 않고 이동 상태·속도·위치를 함께 확인한다.

## 원본 드로잉 코드와의 연결

실제 실행 파일은 `ros2_ws/src/art_artwork_pipeline/art_artwork_pipeline/draw_image_standalone.py`이다. 필압·측정 함수와 기존 장비 상수를 보존했다. `live_control.py`는 이 파일의 UI 실행 모션을 비동기 이동과 상태 관측으로 감싼다. `standalone_drawer.py`는 별도 프로세스에 JSON 제어 명령을 보내고 구조화된 상태만 신뢰한다.

UI에서는 DrawingPlan의 종이 mm 좌표·펜·레이어·실행 순서를 유지한다. 원본의 이미지 재벡터화·바운딩박스 확대·펜 재배정은 UI 실행 경로에서 사용하지 않는다. 선분 단위 이동을 사용하므로 원본의 곡선 일괄 이동과 속도·그림 품질은 실물에서 다시 확인해야 한다. 원본의 직접 이미지 CLI는 유지했다.

묘사 슬라이더는 0~100을 전달한다. CV에서는 경계 검출·필터 설정, DL에서는 후처리 임계값·작은 영역 제거 등에 반영한다. 기존 `low`, `medium`, `high` 입력도 호환한다. 사진마다 선 개수가 단조롭게 증가하는 것을 보장하는 기능은 아니다.

## 빌드

기존 Kiosk·Bridge·Pipeline·드로잉 프로세스를 먼저 종료한다. 메시지에 길이·외력·회차 필드를 추가했으므로 전체 패키지를 빌드하고 모든 터미널에서 새 overlay를 읽어야 한다.

```bash
cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
colcon build --symlink-install
source install/setup.bash
```

## 실물 실행 전 준비

기존 파일 `~/.ros/plane_calibration.json`, `~/.ros/pen_slots.json`, `~/.ros/stick_slot.json`이 필요하다. 현재 PC에서 이 파일들은 확인되지 않았다. 임의 숫자로 만들어 사용하지 말고 실제 측정 파일을 준비한다. 3개 펜 슬롯, 9점 기준면, 스틱 위치와 계획이 종이 안전 영역 안에 들어가는지 실행 전에 검사한다.

추가 제어 설정의 예시는 아래 파일이다.

`ros2_ws/src/art_artwork_pipeline/config/motion_control.example.json`

실제 측정한 `force_bias`, `force_limits` 6개와 펜을 든 홈 왕복 경로를 검증한 뒤 별도 파일에 기록한다. 힘 성분은 N, 토크 성분은 Nm인 드라이버 측정값을 사용한다. 예시의 `null`이나 `validated=false` 상태로는 실행을 거절한다. 확인 없이 `validated=true`로 바꾸지 않는다.

기존 상수 `HOME_JOINTS`, `TOOL_NAME`, `TCP_NAME`, 펜 Z 오프셋과 RG2 디지털 출력이 실제 장비와 일치하는지도 로봇 담당자가 확인한다. 자동 기준면 측정은 실제 접촉 이동을 수행한다. `skip_cal:=true`는 기존 9점 자동 측정만 생략하며 모든 접촉 측정을 생략하는 옵션이 아니다.

드라이버는 기존에 사용하던 M0609 실물 실행 명령으로 별도 실행한다. 프로젝트와 드라이버의 `ROS_DOMAIN_ID`, 로봇 네임스페이스가 일치해야 한다. 이 문서는 확인되지 않은 드라이버 접속 IP를 지정하지 않는다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
source ros2_ws/install/setup.bash
export ART_JOB_PLAN_ROOT="$HOME/A4/data/jobs"
export ART_LINEART_METHOD=cv
export ART_MOTION_CONTROL_CONFIG="$HOME/.ros/a4_motion_control.json"
ros2 launch art_bringup art_system.launch.py
```

`http://localhost:8000`에서 사진·문구·묘사 수준을 입력한다. 카메라는 브라우저에서 허용한다. 실물 드라이버 없이 화면/경로만 볼 때는 그리기 버튼을 누르지 않는다. `dry_run:=true`는 물리 실행 성공으로 표시하지 않는다.

## 자체 시험과 현장 확인

아래 명령은 격리된 도메인 99에서 가짜 SDK·시험용 프로세스를 사용한다. 실물 실행 터미널에 `local_test_env.bash`를 적용하지 않는다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
source ros2_ws/install/setup.bash
source scripts/local_test_env.bash
PYTHONPATH="/tmp/a4-hmi-js-check:$PYTHONPATH" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 -m pytest -c /dev/null --rootdir=. -o cache_dir=/tmp/a4-pytest-cache tests -q -rs
```

`/tmp/a4-hmi-js-check`는 현재 PC의 QuickJS 설치 위치이다. 다른 PC에서는 해당 경로에 의존하지 말고 사용하는 Python 환경에 `quickjs`를 설치한다. 없으면 JS 시험이 건너뛰어지므로 결과를 확인한다.

검증 항목은 UI 버튼·중복 요청·상태 불명 차단, 실제 ROS 서비스·토픽과 시험용 자식 프로세스 통신, 제공된 드로잉 함수의 가짜 SDK 실행, 획 중간 정지·홈·복귀, 외력 후 재개 금지·초기화, 길이 비율, 좌표·펜·레이어 보존, 기존 선화·계획·파일 격리이다.

실물 시험은 아직 수행하지 않았다. 현장에서는 먼저 펜을 종이에 대지 않는 낮은 속도의 홈 왕복과 중단점 복귀를 확인한 뒤 짧은 직선 → 긴 직선의 중간 일시정지 → 재개 → 초기화 순서로 진행한다. 외력 기능은 로봇 담당자의 승인된 시험 방법으로 검증한다. 보호 정지를 임의 해제하거나 로봇을 손으로 밀어 검증하지 않는다.

## 이번 로컬 검증 결과

작업 전 테스트는 제거된 `art_job_manager`를 참조하여 수집 오류 3건이 발생했다. 해당 HTTP 테스트의 의존성을 시험 전용 메모리 백엔드로 바꾸고 기존 검증 항목을 유지했다.

- 전체 회귀 시험: `112 passed`, 실패 0, 건너뜀 0. 실행 로그: `/tmp/a4-redo-regression.log`.
- ROS2 전체 빌드: 5개 패키지 성공. 실행 로그: `/tmp/a4-redo-final-build.log`.
- `python3 -m compileall -q ros2_ws/src tests`: 성공.
- `python3 -m art_artwork_pipeline.lineart.cli --help`: 성공.
- `ros2 interface show art_interfaces/msg/JobStatus`: 생성된 길이·외력·회차·명령 결과 필드 확인.

추가 통합 시험 중 발생한 두 실패는 시험 계획의 종이 여백이 실제 20mm 안전 영역보다 작았던 입력과, 외력 주입 전에 가짜 이동이 끝나는 시험 타이밍이었다. 여백을 실제 제약에 맞추고 시험 전용 이동 대기를 사용해 수정했다. 운영 코드의 안전 검사를 완화하지 않았다.

이번 실행에서 OpenCV 변환과 묘사 값 반영을 검증했다. DL 모델의 실제 추론, 실물 M0609/RG2 동작, 실제 홈 왕복·펜 교체·접촉 측정·외력 정지는 검증하지 않았다. 현재 로컬 폴더에는 `.git`이 없으며 GitHub에는 반영하지 않았다.
