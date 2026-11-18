> 후속 코드 점검에서 모듈을 통합하고 진단 기능을 추가했습니다. 현재 구조와 최신 시험 결과는 [로컬 코드 점검 결과](LOCAL_ROBOT_AUDIT_KR.md)를 확인하세요. 아래 시험 수는 최초 통합 당시 기록입니다.

# 참고 코드 통합 결과와 직접 실행 방법

## 이번에 반영한 기능

2026년 11월 17일 로컬 A4를 기준으로 세 참고 경로의 필요한 기능만 통합했습니다. 참고 폴더와 기존 사진·데이터는 수정하지 않았습니다.

- `Downloads/A4-sub/phase1_kiosk`: 가로 A4 297×210mm, 사방 20mm 사진 배치와 카메라 가로 크롭을 반영했습니다. 사진 비율을 유지하며 891×630 픽셀 캔버스에 배치합니다.
- `Downloads/A4-sub/phase2_lib_lineart/lineart_mfl_ld.py`: MediaPipe 얼굴 영역에는 Canny, 나머지에는 실제 LineartDetector 결과를 합성합니다. 얼굴이 없으면 같은 DL 결과를 사용합니다. 모델 오류를 CV 성공으로 바꾸지 않습니다.
- `Downloads/A4-bae/src/collaborate1/collaborate1/app/draw_image_standalone.py`: 펜 집기·반납, DO1/DO2 제어 순서, 평면 보정 좌표, 모서리 분할과 선택적 스플라인 이동을 현재 ROS Action 실행기로 분리했습니다.

사용자는 사진과 영문 문구를 넣고 미리보기가 준비되면 **그리기**를 누릅니다. 관리자는 현재 작업의 일시정지·재개·중단을 수행합니다. 미리보기만으로 로봇 작업을 시작하지 않습니다.

문구가 있으면 가로 A4 하단에 별도 영역을 확보합니다. 기존 세로 DrawingPlan도 계속 검증하지만, 실행 시 계획 방향과 실제 장비 프로필 방향은 같아야 합니다.

## 제외한 참고 코드

DrawingController에는 사진 변환·벡터 추출·후처리·바운딩박스 재확대·색상 재배정을 넣지 않았습니다. 이 기능은 ArtworkPipeline이 소유합니다. 이미 확정한 계획의 좌표 크기, 펜, 레이어, 실행 순서를 실행기에서 바꾸지 않습니다. 선화 방식이 바뀌면 이전 CV 미리보기를 재사용하지 않고 새 모델로 처리합니다.

자동 9점 접촉 탐색, 기준 막대 측정, 임의 홈 이동은 실행 경로에 연결하지 않았습니다. 기존 필압 관련 코드는 변경하지 않았으며, 이번 실행기는 저장된 평면과 펜별 Z 오프셋을 사용합니다. 실물 필압 제어가 완성됐다는 의미가 아닙니다.

## 핵심 파일

- `art_artwork_pipeline/paper.py`: 용지 크기·사진 여백·문구 영역의 공통 기준입니다.
- `art_artwork_pipeline/lineart/lineart_mfl_ld.py`: 참고 혼합 선화 알고리즘을 패키지 import와 명시적 모델 경로로 옮겼습니다.
- `art_artwork_pipeline/pipeline_runner.py`: 혼합 모델을 별도 Python 프로세스로 호출하고 DrawingPlan·SVG를 생성합니다.
- `art_kiosk/workflow.py`, `static/app.js`: 가로 배치 요청과 카메라 입력을 연결합니다.
- `art_job_manager/plan.py`: v0.2 가로·세로 A4를 검증합니다. SQLite·SHA-256·체크포인트 계약은 유지합니다.
- `art_drawing_controller/equipment_settings.py`: 실물 프로필 검증과 참고 보정 파일의 후보 변환을 담당합니다.
- `art_drawing_controller/doosan_adapter.py`: 실제 `dsr_msgs2` 서비스로 비동기 이동·위치·속도·Tool/TCP·디지털 I/O를 연결합니다.
- `art_drawing_controller/stroke_executor.py`: 확정 획을 순서대로 실행하며 실제 목표 도달 후에만 완료를 보고합니다.
- 펜 교체·개폐 확인·종이 좌표 변환은 `art_drawing_controller/stroke_executor.py`에 통합했습니다. 기존 세 개의 얇은 모듈은 제거했습니다.
- `art_drawing_controller/live_motion.py`: 같은 Action·비동기 이동을 유지하며 일시정지·재개합니다. 중단 요청은 새 이동 제출을 차단합니다.

스플라인은 별도로 실물 검증한 프로필에서만 활성화하며 한 번에 최대 80점을 전달합니다. 기본은 점 사이 직선 이동입니다. 일시정지 시 획을 새로 제출하지 않고 두산 MovePause/MoveResume로 현재 이동의 나머지를 이어갑니다. 서비스 수락만으로 정지·재개·펜 이격을 성공으로 처리하지 않습니다.

## 선화 실행 환경 설치

Ubuntu 24.04 / Python 3.12 기준입니다. ROS 기본 Python에 PyTorch·MediaPipe를 설치하지 않습니다.

```bash
cd ~/A4
bash scripts/setup_lineart_env.bash
export ART_DL_PYTHON="$HOME/.venvs/a4-lineart/bin/python"
export ART_FACE_MODEL_PATH="$HOME/.cache/a4/models/face_landmarker.task"
export ART_LINEART_METHOD=mfl_ld
```

현재 로컬에는 위 가상환경을 설치했고, 제공된 얼굴 모델을 위 캐시 경로에 복사했습니다. 모델은 Git에 포함하지 않습니다. 다른 PC에서는 제공된 모델을 같은 경로에 복사하거나 다음 공식 주소에서 명시적으로 설치합니다.

```bash
mkdir -p "$HOME/.cache/a4/models"
curl --fail --location \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task \
  --output "$HOME/.cache/a4/models/face_landmarker.task"
```

LineartDetector는 최초 실행 때 `lllyasviel/Annotators` 가중치를 내려받을 수 있습니다. 운영 전 네트워크가 가능한 준비 환경에서 먼저 변환을 실행해 캐시를 준비하세요. 얼굴 모델은 요청 처리 중 자동으로 다운로드하지 않습니다.

```bash
"$HOME/.venvs/a4-lineart/bin/python" -m art_artwork_pipeline.lineart.cli \
  --input /실제/사진.jpg --method mfl_ld --resolution 512 --binarize \
  --output-dir /tmp/a4-lineart-check
```

CPU PyTorch 2.6.0, torchvision 0.21.0, MediaPipe 0.10.21, controlnet-aux 0.0.10, NumPy 1.26.4에서 추론을 확인했습니다. 전체 설치 조합은 `requirements-dl-lock.txt`에 기록했습니다. MediaPipe와 controlnet-aux의 서로 다른 OpenCV 배포 의존성은 같은 4.11.0.86 버전으로 고정했습니다. 이 가상환경에서 OpenCV 패키지 하나만 개별 제거하면 공유 `cv2` 파일이 지워질 수 있으므로 환경 전체를 재설치하세요.

현재 외부 두산 overlay를 포함한 전체 Python 메타데이터 검사에서는 기존 `onrobot-rg-control 2.0.0`의 `pymodbustcp` 누락도 발견했습니다. 이번 실행기는 해당 Modbus 패키지를 import하지 않고 두산 디지털 I/O 서비스를 사용합니다. 팀원이 별도로 그 패키지를 실행한다면 외부 워크스페이스의 의존성을 추가 확인해야 합니다.

## 웹과 Fake 시험

각 터미널에서 아래 공통 환경을 먼저 적용합니다. 실제 드라이버를 실행하는 명령은 포함하지 않습니다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
source scripts/local_test_env.bash
export ART_JOB_PLAN_ROOT="$HOME/A4/data/jobs"
export ART_LINEART_METHOD=mfl_ld
export ART_DL_PYTHON="$HOME/.venvs/a4-lineart/bin/python"
unset ART_EQUIPMENT_PROFILE
```

빌드는 다음과 같습니다. 두산 메시지를 사용하는 시험에는 로컬 두산 워크스페이스도 먼저 source 합니다.

```bash
cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
colcon build --symlink-install
```

첫 터미널에서 전체 소프트웨어를 실행합니다.

```bash
ros2 launch art_bringup art_system.launch.py start_controller:=false
```

두 번째 터미널에서는 같은 공통 환경을 적용하고 테스트 전용 Fake를 실행합니다.

```bash
python3 ~/A4/tests/job_manager_v1/fake_drawing_controller.py
```

`http://127.0.0.1:8000`에서 사진·문구 입력 → SVG 확인 → 그리기를 시험하고 `/admin`에서 일시정지·재개·중단을 확인하세요. 이전 서버가 실행 중이면 먼저 정상 종료하고 새 코드를 실행하세요. Fake 완료는 실물 검증 결과가 아닙니다.

모델 없이 UI·통신만 시험하려면 Launch 전에 `export ART_LINEART_METHOD=cv`로 명시합니다. 이 경우 혼합 모델 추론을 시험한 것은 아닙니다.

## 실물 실행 전 남은 확인

실물 검증 프로필이 없으면 Controller는 Goal을 거절합니다. `hardware_validated`를 임의로 true로 바꾸는 것은 검증이 아닙니다.

- 현재 장착한 펜·종이 원점·평면·각 펜의 Z 오프셋을 실제로 측정해야 합니다.
- M0609 Tool/TCP 이름, 실제 기준 좌표, 이동 가능한 XYZ 공간, 안전 이동 높이와 슬롯 경로를 확인해야 합니다. XYZ 범위 검사만으로 충돌·관절 한계가 검증되지는 않습니다.
- DO1/DO2는 참고 코드와 같지만, 실제 파지·열림 확인 DI 배선 정보가 없습니다. 이를 추정하지 않았습니다. RG2 상태 피드백을 제공하는 실제 연결을 확인해야 합니다.
- 설치 드라이버의 비동기 MoveLine·선택적 MoveSplineTask 및 V2.12.1 장비에서의 중간 일시정지·재개를 저속·비접촉부터 검증해야 합니다.
- 통신 단절 시 소프트웨어가 정지를 요청하더라도 장비가 실제로 정지했는지 응답 없이 보장할 수 없습니다. 컨트롤러의 안전 설정·비상정지와 통신 감시도 별도로 검증해야 합니다.

참고 백업은 `data/equipment/reference_profile_unvalidated.json`에 **검증 전 후보**로 변환했습니다. 파일에는 확인되지 않은 Z 오프셋·작업 공간·DI 채널이 비어 있어 그대로 실행할 수 없습니다. 장비별 설정이므로 Git에서 제외합니다.

다른 백업을 변환할 때도 후보 파일만 생성하며, 기존 파일을 덮어쓰지 않습니다.

```bash
ros2 run art_drawing_controller import_equipment_profile \
  --plane /보정/plane_calibration.json --pens /보정/pen_slots.json \
  --output "$HOME/A4/data/equipment/새_후보.json"
```

참고 소스의 라이선스·모델 이용 조건은 별도 배포 전에 확인해야 합니다. 이번 로컬 통합과 테스트가 외부 모델의 재배포 허가를 검증한 것은 아닙니다.

## 검증 기록

최종 자동 시험 수와 실행 명령은 아래에 기록합니다. 모델 추론과 실물 시험은 구분합니다.

### 자동 회귀 시험

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
source ros2_ws/install/setup.bash
source scripts/local_test_env.bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ROS_DOMAIN_ID=99 \
  /tmp/a4-review-venv/bin/python -m pytest tests -q --tb=short
```

결과: **163개 통과, 0개 실패, 1개 건너뜀**, 94.34초입니다. 건너뛴 항목은 별도 외부 HTTP 서버와 `RUN_LIVE_KIOSK_TEST=1`을 요구하는 선택 시험입니다. 같은 프로세스의 ASGI 응답성과 실제 ROS 통합 시험은 실행했습니다.

새 검증은 가로 여백·문구 분리·가로 계획의 JobManager 로딩, 실제 Canny 합성, 보정 프로필 미검증 거절·변경 감지, 좌표 크기와 펜 보존, 스플라인 분할, 실제 설치된 두산 메시지의 이동 요청 필드, 획 중간 일시정지·재개·중단입니다. 모션 관측에는 시험 전용 RecordingAdapter를 주입했으며 실제 로봇을 움직이지 않았습니다.

기존 오프라인 HMI 시험은 모델 없이 실행되도록 `ART_LINEART_METHOD=cv`를 시험 설정에 명시했습니다. 가로 변환으로 획 수가 늘어난 통합 시험은 고정 대기 횟수 대신 실제 획 수에 맞춰 기다리도록 수정했습니다. 운영 실행기의 속도를 시험에 맞춰 변경하지 않았습니다.

### 실제 모델과 계획 생성

제공된 `samples/person1.jpg`를 사용해 실제 혼합 모델 추론을 실행했습니다. MediaPipe는 얼굴 1개를 검출했습니다. 별도 PipelineRunner 실행에서 다음 결과를 확인했습니다.

- 선화: 891×630 픽셀, 사방 20mm 배치입니다.
- 계획: 297×210mm, `artwork`와 `calligraphy` 레이어, 문구 `Hello`, 277개 획입니다.
- 결과: SVG 생성과 JobManager의 DrawingPlan 로딩·SHA-256 검증을 통과했습니다.
- 전체 처리 시간: 해당 실행에서 13.98초였습니다. 사진과 CPU 부하에 따라 달라집니다.
- 시험 결과 위치: `/tmp/a4-reference-integration-onko6wat/REFERENCE_MFL/`입니다. `/tmp`는 재부팅·정리 시 사라질 수 있습니다.
- 얼굴 모델 SHA-256: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`입니다.

모델 추론 성공은 모든 사진의 선화 품질이나 실물 그림 품질을 보장하지 않습니다. SVG를 확인하고 사진 종류별 직접 시험이 필요합니다.

### 빌드와 인터페이스

`ros2_ws`에서 `colcon build --symlink-install --base-paths src`를 실행해 **7개 패키지가 완료**됐습니다. 설치 환경에서 `PrepareArtwork`, `ExecuteDrawing` 인터페이스 조회와 7개 `art_` 패키지 검색을 확인했습니다. 기존 Action 필드는 변경하지 않았으며 PrepareArtwork의 주석과 허용 방식·용지 값만 확장했습니다.

ROS overlay의 패키지 메타데이터가 섞이지 않도록 `env -u PYTHONPATH "$HOME/.venvs/a4-lineart/bin/python" -m pip check`로 검사한 DL 전용 환경은 `No broken requirements found`였습니다. Python 구문 검사, 설치된 CLI의 도움말, 설치 스크립트 구문 검사와 `git diff --check`도 실행했습니다.

### 실행하지 않은 검증

실제 M0609/RG2 이동, 종이 접촉·필압, 펜 교체, 물리 정지·중간 재개, 스플라인 추종 품질은 시험하지 않았습니다. 로봇·안전 제어기·DRFL·드라이버 전체 버전 조합의 실물 호환성도 확정하지 않았습니다. 이번 통합은 검증 프로필을 요구하는 실행 코드를 연결한 것이며 실물 검증 완료 보고가 아닙니다.
