# 자동 사용자·관리자 HMI 직접 시험

사용자 화면은 사진 촬영/첨부와 영문 문구를 받아 경로를 자동 생성한다.
사용자가 SVG 경로를 확인하고 **그리기**를 누르면 작업을 한 번 등록한다.
관리자는 화면 접속 후 현재 작업의 사진·문구·경로·진행률을 자동으로 보고
일시정지·재개·작업중단만 조작한다. 화면에서 작업 ID를 입력할 필요가 없다.

## 1. 이전 프로그램 종료 및 빌드

이전에 켜 둔 Kiosk, Bridge, Pipeline, JobManager, Controller/Fake를 각 터미널에서 Ctrl+C로 종료한다.
실행 중인 프로세스는 이번 코드 수정으로 자동 교체되지 않는다.

```bash
cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

## 로컬 시험의 통신 환경 분리

각 실행 터미널에서 setup.bash를 읽은 뒤 scripts/local_test_env.bash를 읽는다.
기존 ROS_DISCOVERY_SERVER·ROS_SUPER_CLIENT·ROS_STATIC_PEERS 설정을 해제하고
ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST로 같은 PC에서만 노드를 찾게 한다.
환경변수를 바꿔도 이미 실행 중인 프로그램에는 적용되지 않으므로 기존 Launch와 Fake를 종료한 뒤 다시 실행해야 한다.
이 설정은 로컬 Fake 시험용이다. 다른 PC의 실물 장비와 연결하는 운영 설정에 그대로 적용하지 않는다.

## 2. 터미널 1: 웹·Pipeline·JobManager 실행

관리자 인증키는 사용하지 않는다. `/admin`에 접속하면 현재 작업을 바로 조회한다.
새 시험 폴더를 사용하므로 이전 `/tmp/a4-manual-01`의 DB·작업에는 영향을 주지 않는다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

source scripts/local_test_env.bash
export ROS_DOMAIN_ID=97
export ART_JOB_PLAN_ROOT=/tmp/a4-hmi-v2-01/jobs
export ART_JOB_DB=/tmp/a4-hmi-v2-01/jobs.db
export ART_LINEART_METHOD=cv

ros2 launch art_bringup art_system.launch.py start_controller:=false
```

`start_controller:=false`는 거절 전용 Controller를 끄는 옵션이다.
이 시험에서는 다음 Fake만 `/art/execute_drawing`을 제공해야 한다.
기본 Launch의 Controller와 Fake를 같은 Action 이름으로 동시에 실행하지 않는다.

## 3. 터미널 2: 시험 전용 Fake 실행

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

source scripts/local_test_env.bash
export ROS_DOMAIN_ID=97
export A4_ENABLE_FAKE_CONTROLLER=YES
export A4_FAKE_STROKE_SECONDS=2

python3 tests/job_manager_v1/fake_drawing_controller.py
```

Fake는 실제 로봇·RG2를 움직이지 않는다. 2초/획은 버튼 조작 시간을 확보하기 위한 값이다.
서로 다른 프로그램의 ROS_DOMAIN_ID가 다르면 연결되지 않는다.

## 4. 사용자 화면 시험

브라우저에서 `http://127.0.0.1:8000`을 연다. 이전 화면이 보이면 Ctrl+Shift+R로 새로고침한다.

1. 사진을 첨부하거나 카메라를 켜고 촬영한다.
2. 문구에 `Hi` 또는 `My Love`를 입력한다. 문구는 생략할 수 있다.
3. 마지막 입력 후 약 0.6초가 지나면 경로 생성이 시작된다.
4. 최종 경로가 오른쪽에 표시되고 그리기 버튼이 활성화되는지 확인한다.
5. 문구를 바꿔 이전 경로가 숨겨지고, 새 경로가 자동 생성되는지 확인한다.
6. 그림은 상단, 문구는 하단에 있는지 확인한다.
7. 그리기를 한 번 누르면 별도 ID·계획 등록 없이 진행률이 표시되는지 확인한다.

이미지 준비 중에는 실제 드로잉 진행률을 만들지 않는다.
드로잉 진행률은 Controller가 확인한 완료 획 수 / 전체 획 수이다.
새로고침해도 서버의 현재 작업을 다시 조회한다. 같은 탭의 준비 요청 정보는 sessionStorage에 남는다.
별도 새 브라우저는 기존 미리보기의 실행 티켓을 자동으로 얻지 않으며 새 입력을 만들 수 있다.

현재 문구는 영문 대소문자·공백만 지원한다. 숫자·한글·문장부호는 거절한다.
하단 공간에 들어가지 않는 긴 문구는 짧게 입력해야 한다.
CV 엔진에서는 DL 디테일 프리셋에 따른 차이가 없다.

## 5. 관리자 화면 시험

`http://127.0.0.1:8000/admin`에 접속한다. 인증키 입력 없이 현재 작업이 표시된다.

- 작업 ID를 입력하지 않아도 현재 사진·문구·SVG·진행률이 표시되어야 한다.
- 사용자 그리기 클릭 전에는 승인 대기로 표시되고 제어 버튼은 비활성화되어야 한다.
- DRAWING에서 일시정지 → PAUSING → PAUSED를 확인한다.
- PAUSED에서 완료 획 수가 멈추는지 확인한다.
- 재개하면 멈춘 획의 남은 구간부터 같은 Action에서 진행되어야 한다.
- 작업중단 → STOPPING → STOPPED를 확인한다.
- 완료 또는 중단이 확인된 후 사용자 화면에서 다음 사진을 입력할 수 있어야 한다.
- 새 작업을 끝까지 실행해 COMPLETED와 완료 획 수 일치를 확인한다.

Fake는 획 중간 진행을 멈추고 같은 Action에서 이어간다. 재개 중에는 RESUMING으로 표시되며 새 Goal은 생성하지 않는다.
일시정지 중 완료 획 수는 늘지 않으며, 중단은 별도의 Action 취소로 처리한다.
미확정 명령의 요청 ID는 중복 제어 방지를 위해 유지한다.
통신이 끊기거나 상태가 만료되면 진행률을 숨기고 제어 버튼을 비활성화한다.

## 6. 단일 작업·재시작 시험

실행 중·일시정지 중에는 다른 사진으로 작업을 교체할 수 없다.
같은 그리기 요청을 반복해도 같은 작업을 다시 등록하지 않는다.
사진·문구를 수정하면 새 job_id로 새 계획을 만들고 과거 계획은 덮어쓰지 않는다.
문구만 수정하면 이전 선화를 재사용하고 경로를 다시 만든다.

작업 도중 JobManager를 종료·재시작하면 RECOVERY_REQUIRED로 보호하며 자동 재개하지 않는다.
현재 운영자 복구 해제 API는 없다. 실물 상태를 확인하지 않고 이 기록을 삭제하면 안 된다.
Fake 시험을 새로 시작하려면 모든 시험 프로그램을 종료한 후 터미널 1의 경로를
`/tmp/a4-hmi-v2-02/jobs`, `/tmp/a4-hmi-v2-02/jobs.db`처럼 새 폴더로 바꾼다.

## 7. 파일과 오류 확인

```text
/tmp/a4-hmi-v2-01/jobs/
├── .current_workflow.json      # 현재 입력·준비·등록 상태와 실행 티켓
├── .workflow.lock              # 단일 요청 처리 파일 잠금
└── <job_id>/
    ├── photo.png
    ├── lineart.png
    ├── job_metadata.json       # 문구·미리보기 요청·사용자 승인
    ├── preview.svg
    └── drawing_plan.json
```

이 파일들은 런타임 상태이다. 프로세스 실행 중 수정·삭제하지 않는다.

### 이전 화면이 계속 보일 때

기존 Kiosk 서버를 실행한 터미널에서 Ctrl+C로 종료하고 새 코드를 실행한다.
브라우저에서는 Ctrl+Shift+R을 눌러 이전 화면과 스크립트 대신 최신 파일을 불러온다.

### 포트를 이미 사용 중이라고 나올 때

이전에 실행한 Kiosk 또는 Bridge가 남아 있는지 확인한다.
기존 프로그램을 종료한 뒤 다시 실행한다.

### 작업이 대기 상태에서 진행되지 않을 때 (`QUEUED`)

Fake Controller가 실행 중인지 확인한다.
Fake와 다른 노드의 `ROS_DOMAIN_ID`가 모두 같은지도 확인한다.

### 계속 그리기 승인 대기로 표시될 때

사용자 화면에서 최종 경로를 확인한 뒤 **그리기** 버튼을 눌렀는지 확인한다.
미리보기가 만들어진 것만으로는 작업이 시작되지 않는다.

### 문구가 너무 길다는 오류가 나올 때

문구가 종이 하단 영역에 들어가도록 영문 문구를 짧게 바꾼다.

### /tmp 시험 폴더를 찾지 못한다는 오류가 나오지만 로컬에는 폴더가 있을 때

외부 Discovery Server 설정 때문에 다른 PC의 Pipeline이 로컬 파일 경로를 처리하는지 확인한다.
같은 도메인에서 ArtworkPipeline·JobManager·Controller가 중복 발견되면 실행을 계속하지 않는다.
기존 Launch와 Fake를 종료하고 각 터미널에서 scripts/local_test_env.bash를 읽은 뒤 다시 실행한다.
폴더를 무작정 삭제하거나 다른 PC에 동일 경로를 만드는 방식으로 해결하지 않는다.
Bridge는 중복 Pipeline·JobManager 요청을 거절하고 Manager는 중복 Controller에 Goal을 보내지 않는다.

### 입력 사진에서 그릴 경로를 찾지 못할 때

배경과 피사체의 대비가 뚜렷한 다른 사진으로 다시 입력한다.

### 이미지 처리 결과가 미확정일 때 (`UNKNOWN_PREPARATION`)

원격 이미지 처리가 끝났는지 아직 확인되지 않은 상태다.
완료된 DrawingPlan이 있으면 현재 상태를 조회할 때 미리보기를 복구한다.
결과 파일이 없으면 운영자가 처리 상태를 확인해야 한다.

### 작업 등록 결과가 미확정일 때 (`UNKNOWN_SUBMISSION`)

등록 요청이 전달되었을 수 있으므로 새 작업 ID로 다시 등록하지 않는다.
현재 작업을 조회해 기존 요청이 등록되었는지 확인한다.

### 실제 상태 확인이 필요할 때 (`RECOVERY_REQUIRED`)

작업의 실제 실행 상태를 운영자가 확인해야 한다.
이 상태에서는 자동으로 재개하거나 새 작업을 시작하지 않는다.

## 8. 자동 시험 재실행

실행 중인 사용자 시험과 분리하기 위해 자동 시험은 도메인 99를 사용한다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
source scripts/local_test_env.bash
PYTHONPATH="/tmp/a4-hmi-js-check:$PYTHONPATH" \
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ROS_DOMAIN_ID=99 \
python3 -m pytest -c /dev/null --rootdir=. -o cache_dir=/tmp/a4-live-hmi-pytest tests -q -rs
```

QuickJS가 없으면 프런트엔드 동작 시험이 건너뛰어진다. 이번 검증에는 임시 경로의 QuickJS를 사용했다.
별도 Fake를 도메인 99에 띄우지 않는다. 자동 시험이 직접 서버를 생성한다.

## 구현과 검증 범위

현재 작업 관리: `art_kiosk/workflow.py`. 상태의 최종 기준은 기존 JobManager이다.
신규 API: `/api/kiosk/prepare`, `/api/kiosk/preview`, `/api/kiosk/draw`, `/api/kiosk/current`,
`/api/admin/current`, `/api/admin/current/control`과 현재 작업 미디어 조회.
사용자 시작 API는 임의 계획 경로를 받지 않으며 현재 미리보기 티켓과 계획 SHA를 확인한다.
구형 관리자 등록 API는 새 워크플로 기록이 있는 경우 우회 등록을 거절한다.
기존 인터페이스 필드는 유지하며, 동일 실행 제어용 ControlDrawing 서비스와 live 상태 처리를 추가했다.

실물 Controller는 계속 모든 Goal을 거절한다. Fake 성공은 실물 검증을 의미하지 않는다.
실제 브라우저 카메라 권한·레이아웃·DL 추론·물리 동작은 사용 환경에서 별도 확인해야 한다.

## 이번 변경의 실제 검증 결과

- 전체 회귀 시험: **129 passed, 0 failed, 1 skipped (13.97초)**.
- 유일한 skip: `RUN_LIVE_KIOSK_TEST=1`이 필요한 기존 외부 라이브 키오스크 반응성 시험.
- ROS2 빌드: `colcon build --symlink-install`, 7 packages finished, 실패 0.
- 실제 별도 프로세스 시험: 도메인 98·포트 18120/18121에서 Launch와 Fake를 실행했다.
  실제 네트워크 HTTP로 사진·문구·SVG·중복 그리기·PAUSE·RESUME·CANCEL·다음 작업 COMPLETED를 확인했다.
  로그는 이번 로컬 환경의 `/tmp/a4-hmi-network-0l1xql3l/`에 있다.
- QuickJS: 카메라 API 모형·사진 첨부·자동 생성·이전 결과 무효화·자동 진행률·상태 만료·관리자 중복 명령 검증.
- JobManager, 기존 ROS 인터페이스, 참고 데이터 파일 변경 없음. GitHub 커밋·푸시는 수행하지 않았다.

## 추가 점검: 외부 Discovery Server가 남아 있던 실행 환경

로컬 시험 폴더를 읽지 못하는 FileNotFoundError를 점검했을 때,
실행 프로세스에 외부 ROS_DISCOVERY_SERVER와 ROS_SUPER_CLIENT=TRUE가 남아 있었다.
같은 도메인에서 ArtworkPipeline·JobManager가 각각 두 개씩 발견됐으며
거절 전용 DrawingController와 Fake도 함께 발견됐다.
로컬에는 오류에 나온 폴더와 이미지·계획 파일이 존재했다.

같은 사진과 hello 문구를 외부 Discovery 설정을 해제한 별도 로컬 프로세스에 입력해
HTTP 200, PREVIEW 상태, SVG와 DrawingPlan 생성 성공을 확인했다.
결과는 /tmp/a4-isolated-upload-check-oqem48v4에 있으며 기존 사용자 시험 데이터는 수정하지 않았다.

Bridge의 중복 Pipeline·JobManager 거절과 Manager의 중복 Controller 배차 차단을 추가했다.
Jazzy의 Node.destroy_node는 ActionServer·ActionClient를 자동 해제하지 않으므로
관련 노드가 종료할 때 Action 객체도 명시적으로 해제하도록 수정했다.

회귀 시험은 로컬 격리 도메인 99에서 155개 통과, 실패 0개, 선택 시험 1개 건너뜀이다.
중복 Pipeline에 입력 파일을 전달하지 않는 검사와 중복 Controller에 Goal을 보내지 않는 검사를 포함한다.
기존 129개 통과 기록은 최초 HMI 변경 당시 기록이며 최신 정지·재개·중복 서버 검사 결과는 이 절을 따른다.
