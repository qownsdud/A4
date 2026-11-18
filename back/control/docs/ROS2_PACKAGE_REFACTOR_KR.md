# ROS2 기능별 패키지 통합 결과와 실행 안내

> 후속 HMI 변경: 사진·영문 문구 → 자동 경로 → 사용자 그리기 승인 → 자동 등록으로 변경했습니다.
> 최신 실행·API·직접 시험은 [자동 HMI 안내](HMI_MANUAL_TEST_KR.md)를 참고하세요.
> 아래 관리자 계획 생성·등록 설명과 검증 수치는 최초 통합 당시 기록입니다.

기준: 2026-11-17, `yongsoo` / `c3a3e18`. 작업 시작 시 `origin/yongsoo`와 차이 0/0.
기존 미추적 `archives/`는 수정·커밋하지 않았다. `jang`, `ryu`는 병합하지 않았다.
`bae`에서는 `cursive_font.py`의 문자 모양과 2D 보간만 선택적으로 가져왔다.

## A. 결과와 설계 결정

- Phase 1의 서버·전처리·관리자 인증·정적 화면을 `art_kiosk`로 이동했다.
- Phase 2/3의 실제 알고리즘은 `art_artwork_pipeline`로 이동했다. 구형 Python 호환 진입점은 후속 정리에서 제거했다. 새 패키지는 과거 Phase 폴더를 import하지 않는다.
- 정적 파일은 `package_data`에 포함했다. 일반 wheel 설치에서도 제공된다.
- 사진 처리에 과거 `.venv/bin/python` 경로를 사용하지 않는다. Kiosk → HTTP Bridge → ROS Action Pipeline으로 연결했다.
- 작업 데이터는 `ART_JOB_PLAN_ROOT/<job_id>/`에 저장한다. 기본값은 `~/A4/data/jobs`이다. 설치된 Python 소스 경로에는 저장하지 않는다.
- 사진 변환 응답의 `X-Job-Id`를 브라우저가 확인 요청까지 보존한다. 작업별 원본과 결과를 덮어쓰지 않는다.
- `LINEART`와 `PLAN`을 나눴다. 선화 생성만으로 계획을 만들지 않고, 계획 생성만으로 JobManager에 등록하지 않는다. 등록 후에는 기존 JobManager가 실행을 배차하므로 등록은 관리자 승인 단계이다.
- 색상은 `puzzle/colors.py`의 6/5/5 배정으로 통합했다. 같은 seed는 같은 배정이다. 최적화가 기존 펜·레이어를 다시 배정하지 않으며 `(pen_id, layer)`별로만 병합한다. 기본 최적화는 획 수를 제한하지 않는다.
- DrawingPlan v0.2, 원자적 hard-link 공개와 덮어쓰기 금지, JobManager의 별도 SHA 검증을 유지했다. 기존 SQLite·상태 머신·체크포인트 코드는 변경하지 않았다.
- DL은 실제 추론 요청 때만 PyTorch와 `controlnet_aux`를 import한다. `ART_DL_PYTHON` 환경에서 같은 패키지 코드를 `-m`으로 실행한다. 모델 실패를 CV 성공으로 숨기지 않는다.
- 영문 대소문자·공백의 2D 필기체를 지원한다. 한글, 숫자, 문장부호는 지원하지 않으며 오류로 반환한다. 기본 위치는 `(15,270)` mm, x-height 8 mm이다. A4 밖으로 나가는 문구는 거절한다.

부분 완료: 실물 Controller의 구조, 계획 검증, 좌표 연산, 안전 거절 경계는 구현했다. 실제 모션·RG2 펜 교체·센서 기반 이격·필압·장비 캘리브레이션은 미구현/미검증이다. `drawing_controller`는 모든 Goal을 거절하며 성공·펜 이격을 꾸며내지 않는다. Bringup의 YAML은 장비 준비 조건을 기록한 참고 설정이며 실물 활성화 스위치가 아니다.

미실행: DL 모델 다운로드/실제 추론, 실물 M0609/RG2, 실제 브라우저 카메라·레이아웃, 외부 서버를 별도로 요구하는 opt-in 라이브 반응성 시험. QuickJS는 최소 DOM 동작 시험이다.

## B. 현재 파일 구조와 후속 정리

구형 Phase 호환 Python 파일·중복 requirements·낡은 README·ZIP 적용 안내를 제거했습니다.
모든 실제 구현은 `ros2_ws/src/`의 7개 패키지에 있습니다.
기존 Phase 3 회귀 시험은 `tests/artwork_pipeline/`로 이동했고 기존 사진·JSON·SVG는
`data/reference/{kiosk,lineart,path_planner}/`로 이동했습니다. 데이터 내용은 보존합니다.
모든 파일별 현재 상태는 [실제 파일 트리](ROS2_REFACTOR_FILE_TREE.txt)를 참고하세요.
아래의 최초 통합 검증 기록은 당시 결과이며 후속 정리 검증 결과는 마지막 절에 기록합니다.

## C. 패키지와 핵심 파일의 역할

**art_interfaces**

- 파일과 책임: 기존 CreateJob/ControlJob/JobStatus/ExecuteDrawing 유지, PrepareArtwork 추가
- 연결: 모든 ROS 노드의 계약

**art_kiosk**

- 파일과 책임: main: Uvicorn 실행, server: 사진·확인·계획 요청·정적 제공, preprocess: 기존 이미지 정규화, hmi_api: 동일 출처 검사·상태·관리자 등록/제어, static: 사용자/관리자 화면
- 연결: loopback Bridge HTTP

**art_kiosk_bridge**

- 파일과 책임: main: HTTP와 ROS executor, http_api: 라우팅, schemas: 입력 계약, bridge_node: ROS service/action client와 상태 구독, errors: 통신 오류
- 연결: Pipeline Action / JobManager service·topic

**art_artwork_pipeline**

- 파일과 책임: pipeline_node: 단일 처리 슬롯과 취소, pipeline_runner: 격리·단계 실행·공개, lineart: CV/DL 변환, path_planner: 추출·종이 mm·최적화·저장·SVG·시각화, puzzle: 단일 색상 배정, calligraphy: 문자 경로
- 연결: PrepareArtwork 제공, 파일로 JobManager와 연결

**art_job_manager**

- 파일과 책임: job_manager_node: 실제 Action client, production_engine: 기존 상태 머신, job_repository: SQLite, plan: 계약·SHA, job_engine/job_manager_test_node: 기존 모형 실행
- 연결: CreateJob/ControlJob 제공, 상태 발행, ExecuteDrawing 요청

**art_drawing_controller**

- 파일과 책임: drawing_node: 거절 전용 Action server, plan_loader: 계약/SHA 재검사, stroke_executor: 재개 순서, paper_transform: 종이→로봇 좌표 순수 연산, motion_safety: XYZ 제한, doosan_adapter/pen_controller: 미검증 하드웨어 차단
- 연결: ExecuteDrawing 제공, 실제 모션 미연결

**art_bringup**

- 파일과 책임: art_system.launch.py: 5개 프로세스 실행, config: 장비·종이·펜 준비 조건 참고
- 연결: 전체 패키지 실행

`paper_transform`의 좌표 연산 시험 통과는 실제 보정값의 정확도 또는 로봇 안전 검증을 뜻하지 않는다.

## D. 전체 실행 흐름과 API 호환성

```text
POST /api/kiosk/photo → job_id 생성·photo.png 저장
 → POST /bridge/artwork → /art/prepare_artwork (LINEART)
 → lineart.png 반환 (PNG 응답 + X-Job-Id)
 → 사용자 확인 POST /api/kiosk/confirm (job_id + 동일한 선화)
 → job_metadata.json confirmed=true
 → 관리자 POST /api/admin/artwork/<job_id>/prepare
 → Bridge → PrepareArtwork (PLAN)
 → Stroke 추출 → A4 mm → 색상 → 최적화 → 영문 문자 → 검증 → preview.svg
 → drawing_plan.json 원자 공개
 → 관리자 검토·등록 POST /api/admin/jobs
 → Bridge → /art/create_job → JobManager SQLite·SHA 검증
 → /art/execute_drawing → 실물 서버는 거절 / 별도 시험 Fake만 모의 완료
 → /art/job_status → Bridge → Kiosk 상태 표시
```

보존: `/api/kiosk/photo` PNG 응답, `/api/kiosk/confirm`, `/api/kiosk/latest`, `/admin`, 기존 관리자 상태·등록·제어 API.

변경: confirm/latest의 파일은 작업별 `lineart.png`이다. 과거 `confirmed_outputs/latest_lineart.png`를 갱신하지 않는다. 과거 이미지도 지우지 않는다. `archived_previous_file`은 항상 null이며 이전 작업 이미지는 각 디렉터리에 보존된다. confirm에 job_id가 없으면 새 작업으로 선화 PNG를 수입하는 호환 동작이다. 이 경우 사진 원본은 없다. capabilities의 `photo_to_drawing_plan`은 true이며 `automatic_job_start`는 false다. 기본 엔진은 CV이며 DL을 사용하려면 설정이 필요하다.

Action의 LINEART/PLAN 외 값은 거절한다. 노드 전체에서 1개 요청만 처리하며 다른 요청은 거절한다. 취소는 알고리즘 단계 사이에 확인한다. 실행 중인 OpenCV 함수 또는 DL subprocess를 즉시 중단하지 않으며 DL은 120초 제한이다. 취소 확인 전 결과 파일은 공개하지 않는다. 계획 공개 이후에는 완료로 응답한다. 처리 실패는 작업을 자동 등록하거나 재시도하지 않는다. 프로세스 비정상 종료로 `.processing`이 남으면 작업자가 프로세스 종료와 미완료 상태를 확인한 뒤 해당 잠금을 정리해야 한다.

경로는 canonical 작업 디렉터리의 `photo.png` 또는 `lineart.png`만 허용하고 다른 작업·심볼릭 링크 입력·`..` ID는 거절한다. Kiosk/Bridge/Pipeline/Manager는 같은 신뢰된 로컬 파일 시스템과 ART_JOB_PLAN_ROOT를 사용해야 한다. Bridge는 기존 설계대로 loopback에 두며 외부 공개용 인증 프록시가 아니다.

## E. 실제 검증 기록

기준 시험 명령:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
PYTHONPATH="$PYTHONPATH" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ROS_DOMAIN_ID=97 \
  python3 -m pytest -c /dev/null tests -q -rs
```

변경 전 **87 passed, 2 skipped**. QuickJS 미설치, opt-in 라이브 시험이 각각 skip이었다. `-c /dev/null`의 초기 캐시 위치 경고는 최종 실행에서 명시적 rootdir/cache_dir로 해결했다.

최종 전체 시험 명령:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
PYTHONPATH="/tmp/a4-hmi-js-check:$PYTHONPATH" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ROS_DOMAIN_ID=97 \
  python3 -m pytest -c /dev/null --rootdir=. -o cache_dir=/tmp/a4-pytest-cache \
  tests -q -rs
```

최종 집계는 아래 최종 검증 절에 기록한다. QuickJS는 `python3 -m pip install --target /tmp/a4-hmi-js-check quickjs`로 임시 설치하여 기존 프런트엔드 시험을 실제 실행했다.

추가 실행:

```bash
cd ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
ros2 pkg list | rg '^art_'
ros2 interface show art_interfaces/action/ExecuteDrawing
ros2 interface show art_interfaces/action/PrepareArtwork
python3 -m art_artwork_pipeline.lineart.cli --help
python3 -m art_artwork_pipeline.path_planner.cli --help
```

- 빌드: 7 packages finished, 실패 0. 패키지 7개 검색, 두 Action 생성·import, 두 CLI help 성공.
- 일반 설치: `python3 -m pip install --upgrade --no-deps --no-build-isolation --target /tmp/a4-installed-check ros2_ws/src/art_kiosk ros2_ws/src/art_artwork_pipeline`. `/tmp`에서 이 경로를 우선 PYTHONPATH로 사용해 `/`, `/admin`, JS 2개, CSS의 HTTP 200과 Pipeline 모든 모듈 import 성공. DL 모듈 import는 모델 추론을 실행하지 않는다.
- Launch: `ros2 launch art_bringup art_system.launch.py`를 별도 프로세스로 실행, 도메인 98·임시 DB·포트 18090/18091에서 웹 health 두 개와 ROS 노드 4개를 확인하고 종료했다. 물리 작업은 등록하지 않았다.
- 순수 Python/ROS 시험: CV→실 Stroke→A4 mm→SVG→SHA, 원자 공개·재공개 거부, 선화 확인/등록 승인 경계, 작업 격리·잘못된 입력·처리 실패·취소·동시 요청 거절, Kiosk HTTP→실 ROS Pipeline→실 JobManager→Fake→COMPLETED, 실물 Controller Goal 거절.
- 기존 시험: PAUSE/RESUME/CANCEL·중복 요청·응답 유실·SHA 변조·체크포인트·재시작 복구·교차 출처 차단·상태 신선도·프런트엔드 동작 유지.

개발 중 발견·수정: 정적 파일 시험의 구형 경로, Launch의 Bridge 실행 이름(`bridge`), DL 모듈의 eager import. 일반 설치본 갱신 전 구형 wheel을 시험한 실행은 실패 후 최종 wheel로 갱신·재검증했다. Fake를 0.01초/획으로 설정했을 때 완료 피드백보다 결과가 먼저 관측되어 Manager가 RECOVERY_REQUIRED로 보호한 실행이 있었다. 안전 규칙은 완화하지 않고 기존 Fake 기본값 0.25초/획으로 정상 통합 흐름을 검증했다. Launch와 pytest의 같은 도메인 동시 실행 충돌은 도메인 98/97 분리로 해결했다.

## F. Ubuntu 24.04 + ROS2 Jazzy 실행

ROS2 Jazzy를 설치한 환경에서 프로젝트 루트를 `~/A4`로 가정한다. 아래 의존성 설치는 재현용 안내이며 이번 작업에서 apt 설치를 수행한 것은 아니다.

```bash
sudo apt update
sudo apt install python3-colcon-common-extensions python3-rosdep python3-pip python3-venv \
  python3-fastapi python3-uvicorn python3-httpx python3-multipart python3-pil \
  python3-opencv python3-numpy python3-matplotlib python3-scipy python3-pytest
cd ~/A4
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths ros2_ws/src --ignore-src -r -y
cd ros2_ws
colcon build --symlink-install
source install/setup.bash
```

모든 터미널에서 공통 환경을 적용한다:

```bash
source /opt/ros/jazzy/setup.bash
source ~/A4/ros2_ws/install/setup.bash
export ART_JOB_PLAN_ROOT="$HOME/A4/data/jobs"
export ART_JOB_DB="$HOME/A4/data/jobs_real_v1.db"
export ART_LINEART_METHOD=cv
# 관리자 인증키 설정은 필요하지 않다. 기본 로컬 접속을 사용한다.
```

노드별 실행(각 터미널):

```bash
ros2 run art_artwork_pipeline artwork_pipeline
ros2 run art_kiosk_bridge bridge
ros2 run art_job_manager job_manager
ros2 run art_drawing_controller drawing_controller
ros2 run art_kiosk kiosk
```

또는 전체 실행:

```bash
ros2 launch art_bringup art_system.launch.py
```

기본 웹 주소는 `http://127.0.0.1:8000`, 관리자 화면은 `/admin`, 내부 Bridge는 8001이다. 사진 생성→확인 후 표시된 작업 ID를 관리자 계획 생성 폼에 입력한다. 필요하면 영문 문구를 넣는다. 서버의 SVG와 JSON을 검토한 뒤 별도 등록 폼의 승인 체크로 작업 등록을 요청한다. 실물 Controller는 거절하므로 물리 드로잉은 수행되지 않는다.

Fake 시험은 실물 연결 없이 격리 도메인에서 수행한다. 전체 Launch의 거절 전용 Controller와 Fake를 같은 Action 이름으로 동시에 실행하지 않는다.

```bash
cd ~/A4
ROS_DOMAIN_ID=97 A4_ENABLE_FAKE_CONTROLLER=YES \
  python3 tests/job_manager_v1/fake_drawing_controller.py
# 다른 터미널에서도 ROS_DOMAIN_ID=97을 적용하고 Pipeline/Bridge/Manager/Kiosk만 실행한다.
```

pytest 재실행은 E절의 전체 명령을 사용한다. Fake 노드를 따로 띄울 필요가 없다. pytest 실행 시 같은 도메인에서 별도의 시스템 노드를 실행하지 않는다.

DL 선택 환경(실제 추론 미검증):

```bash
python3 -m venv /tmp/a4-dl
/tmp/a4-dl/bin/pip install -r ~/A4/ros2_ws/src/art_artwork_pipeline/requirements-dl.txt
/tmp/a4-dl/bin/pip install --no-deps ~/A4/ros2_ws/src/art_artwork_pipeline
export ART_DL_PYTHON=/tmp/a4-dl/bin/python
export ART_LINEART_METHOD=dl
```

PyTorch/torchvision/controlnet_aux/transformers/OpenCV/Pillow/NumPy는 이 별도 환경에 설치하며 시스템 ROS Python에 DL requirements를 일괄 설치하지 않는다. requirements는 기존 범위 조건을 유지했으며 모든 최신 조합의 호환성이나 GPU/CUDA는 검증하지 않았다. ROS Python의 PYTHONPATH와 DL 환경이 충돌하면 ROS 미포함 환경에서 DL 실행기를 구성해야 한다. 모델 다운로드 및 최초 추론은 별도 확인이 필요하다.

CLI:

```bash
python3 -m art_artwork_pipeline.lineart.cli --input /absolute/photo.png --method cv --paper a4 --output-dir /tmp/a4-preview
python3 -m art_artwork_pipeline.path_planner.cli --input /absolute/lineart.png --out-dir /tmp/a4-vector --job-id CLI_JOB
python3 -m art_artwork_pipeline.path_planner.optimize_existing --help
```

CLI의 직접 입력은 운영자 로컬 도구이다. ROS Action의 허용 입력 루트 제한과 별개다. 계획 등록은 관리자 API에서 따로 수행한다.

## G. Git 반영

대상은 `yongsoo`이며 force push와 다른 기능 브랜치의 전체 병합은 하지 않는다. 최종 커밋 SHA와 push 결과는 작업 완료 응답에 기록한다. `archives/`와 build/install/log·egg-info·실행 DB·새 작업 사진은 포함하지 않는다. 본 문서의 실물 미검증 경계를 유지한 상태로 소프트웨어 검증 결과만 반영한다.

## 최종 검증 집계

2026-11-17 최종 전체 명령 결과: **101 passed, 0 failed, 1 skipped (6.37초)**.
유일한 skip은 `tests/integration/test_pause_during_conversion.py`의 `RUN_LIVE_KIOSK_TEST=1` opt-in 미설정이다.
동일한 반응성 요구는 기존 HMI의 비동기 Pipeline 통신 모형 시험에서 검증했다. 외부 서버를 대상으로 하는 해당 시험을 실행했다고 간주하지 않는다.
`python3 -m compileall -q`로 신규 Python 패키지와 Launch 구문 검사 성공, `git diff --check` 성공.
기존 추적 PNG/JSON/SVG 49개를 유지했으며 새 데이터 파일은 변경 목록에 포함하지 않았다.

## 구형 Phase 파일 제거 후 검증

구형 호환 코드 14개와 중복 requirements, 낡은 Phase README, 적용 완료된 ZIP 패치 안내를 삭제했다.
기존 데이터 48개는 data/reference로 이동했고 이동 전후 SHA-256이 모두 일치한다.
기존 Phase 3 시험 4개는 tests/artwork_pipeline로 이동했으며 테스트 삭제는 없다.
구형 로컬 가상환경·Python 캐시도 제거했다. archives는 변경하지 않았다.
현재 README와 패키지 README를 새 구조로 작성하고 문서의 실행 경로를 수정했다.
전체 pytest를 tests 경로에서 실행한 결과: **101 passed, 0 failed, 1 skipped (6.17초)**.
유일한 skip은 opt-in 라이브 키오스크 시험이다. 실물 로봇 및 DL 추론 검증 범위는 바뀌지 않는다.
