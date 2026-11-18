> 아래는 이전 버전의 기록입니다. 현재 버튼·SQLite·재개 정책은 [중단점 복구와 새 그림 시작](CHECKPOINT_RECOVERY_KR.md)을 우선 적용하세요. 초기화·외력 후 처음부터 그리기와 수동 허용 체크박스는 현재 사용하지 않습니다.

# 실물 드로잉 시작 전 현재 확인 사항

현재 UI는 이전 실행이 미확정이어도 사진·문구와 새 경로를 준비할 수 있습니다. 최신 입력·실행 분리 정책은 [통합 UI 직접 시험](HMI_MANUAL_TEST_KR.md)을 확인하세요.

## 지금까지 확인한 사실

드라이버가 실제 로봇과 연결되어 있으며 `/dsr01/error` 알람 발행자를 확인했다. 이동 없이 조회했던 당시 Tool은 `PenTool Weight`, TCP는 `PenGripper`, 상태는 `3: SAFE_OFF`였다. 총 29개의 힘 값을 읽었지만 SAFE_OFF 상태의 기록이므로 정상 드로잉 기준이나 안전 임계값으로 채택하지 않았다.

운영자는 현재 종이·펜·RG2 배치와 기존 홈 자세의 왕복 경로를 확인했다고 답했다. 제어기의 충돌 감지·보호 정지 설정은 아직 확인하지 못했다고 답했다. 따라서 프로그램이 이 설정을 확인한 것으로 기록하거나 실물 이동을 실행하지 않았다.

보고서는 `data/diagnostics/force-1794973475358533498.json`에 있다. 코드의 시험 결과와 실물 드로잉 시험 결과는 별개이다.

현재 실행 기본값은 사용자의 기존 설정인 `Tool_Weight` / `GripperDA_v1`이다. 위의 조회 기록은 당시 상태이며 현재 사용할 장비 설정을 뜻하지 않는다.

## 이번 코드 변경

`driver_events.py`는 `/dsr01/error`를 별도 ROS 실행기로 구독한다. 제어기의 오류와 안전 경고는 상태가 정상으로 돌아와도 기억한다. 이를 통해 드라이버가 보호 정지를 빠르게 복구하더라도 이미 수신한 알람을 잃지 않는다. 코드 번호와 메시지를 함께 표시하며 모든 알람이 몸체 충돌이라고 추정하지 않는다. 일반 안내 메시지는 정지 사건으로 취급하지 않는다.

`live_control.py`는 이 알람을 모션 전후에 검사하고 정지 확인 후 UI에 외력·보호 정지 상태를 표시한다. 재개는 거절하며 작업자가 초기화를 눌렀을 때만 정상 상태를 확인하고 기록을 지운다. 복구 확인 중 새로운 알람이 생기면 지우지 않는다. 제어기 알람 발행자가 없거나 여러 개이면 실행을 거절한다. 수신되지 않은 사건까지 보장하는 안전 장치는 아니며 제조사의 충돌 감지·비상정지를 대체하지 않는다.

보호 모드는 두 가지다.

- `controller`: 제어기의 충돌 감지·보호 정지를 기본으로 사용한다. 임의의 6축 외력 수치를 요구하지 않는다. 운영자가 홈 왕복과 제어기 설정을 확인한 기록이 필요하다.
- `software_force`: 기존 제어기 상태 감시에 6축 외력 임계값 감시를 추가한다. 기존 설정 파일과 호환되며 실제 측정·검증한 수치가 필요하다.

`draw_image_standalone.py`는 `ART_TOOL_NAME`, `ART_TCP_NAME`으로 장비 이름을 받을 수 있다. 선택된 Tool/TCP가 실행 설정과 다르면 다른 값으로 바꾸기 전에 거절한다. 기존 필압·접촉 측정 함수를 변경하지 않았다.

`inspect_drawing`은 조회만 수행한다. `configure_drawing`은 운영자가 확인한 설정을 파일로 저장할 뿐 제어기 충돌 설정·서보를 바꾸거나 로봇을 움직이지 않는다. 기존 설정 파일을 덮어쓰지 않는다.

## 운영자가 지금 확인할 것

1. 티치펜던트의 안전 설정에서 현재 작업 영역에 적용되는 충돌 감지와 보호 정지 설정을 로봇 담당자와 확인한다. V2.12 계열의 메뉴를 사용하며 다른 버전의 메뉴명을 그대로 가정하지 않는다. 직접 손이나 몸으로 움직이는 로봇을 건드려 검사하지 않는다.
2. 기존 설정으로 복귀하므로 실제 보정에 사용한 Tool/TCP가 `Tool_Weight` / `GripperDA_v1`인지 확인하고 티치펜던트에서 선택한다. 등록 이름만 같다는 이유로 무게·무게중심·TCP 좌표가 정확하다고 간주하지 않는다.
3. 보호 정지·서보 OFF 원인을 확인하고 티치펜던트의 정규 절차로 정상 대기 상태를 준비한다. A4는 강제로 서보를 켜거나 보호 정지를 해제하지 않는다.

## 전체 빌드

기존 A4 Launch를 종료하고 빌드한다. 로봇 드라이버는 중복 실행하지 않는다.

```bash
cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
colcon build --symlink-install
source install/setup.bash
```

## 읽기 전용 점검

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
source ros2_ws/install/setup.bash
unset ROS_DISCOVERY_SERVER ROS_SUPER_CLIENT ROS_STATIC_PEERS ROS_LOCALHOST_ONLY
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export ROS_DOMAIN_ID=40

# 위 이름이 실제 보정과 일치한다고 확인한 후 설정한다.
export ART_TOOL_NAME='Tool_Weight'
export ART_TCP_NAME='GripperDA_v1'
export ART_MOTION_CONTROL_CONFIG="$HOME/.ros/a4_motion_control.json"

ros2 run art_artwork_pipeline inspect_drawing --seconds 10 --label stationary
```

이 명령의 보고서는 실물 검사 합격증이 아니다. 정지 상태 기록만으로 몸체 접촉 감도·정지 거리·정지 시간을 입증할 수 없다. 설정 저장 전에는 설정 파일 누락이 표시되는 것이 정상이다.

## 충돌 설정까지 실제 확인한 다음 설정 저장

아래 두 플래그는 실제 확인한 내용만 기록한다. 아직 확인하지 않았다면 실행하지 않는다.

```bash
ros2 run art_artwork_pipeline configure_drawing \
  --home-path-verified \
  --controller-collision-verified
```

이후 기존 조회 명령을 다시 실행하여 설정 파일, Tool/TCP, 정상 상태와 알람 경로를 확인한다. 현재 설정 확인은 파일 내용의 유효성을 의미하며 제어기 안전 설정을 소프트웨어가 인증했다는 의미는 아니다.

## UI 실행과 첫 그림

같은 터미널에서 실행한다. 다른 터미널이면 위 환경변수와 setup을 다시 적용한다.

```bash
export ART_JOB_PLAN_ROOT="$HOME/A4/data/jobs"
export ART_LINEART_METHOD=cv
ros2 launch art_bringup art_system.launch.py virtual:=false dry_run:=false
```

`http://localhost:8000`에서 단순한 사진과 Low 묘사를 선택해 경로를 생성한다. 정상 이동 공간과 종이·펜 배치를 확인한 뒤 그리기를 누른다. 기존 자동 9점·기준 막대 접촉 측정도 수행할 수 있다. 첫 실행에서는 정상 드로잉을 먼저 확인하고 일시정지 → 홈 → 재개 → 초기화 순서로 검증한다. 초기화는 그림을 즉시 처음부터 다시 그린다.

충돌 시험은 제조사·기관의 승인된 도구와 절차로 수행한다. 물리 정지, UI 경고 유지, 재개 금지, 운영자 초기화 후 재시작을 모두 확인해야 실물 예외 처리 검증으로 기록할 수 있다.

## 이번 검증 결과

- 전체 회귀 시험: `119 passed`, 실패 0, 건너뜀 0. 로그: `/tmp/a4-event-regression.log`.
- ROS2 전체 빌드: 5개 패키지 성공. 로그: `/tmp/a4-event-final-build.log`.
- 두 신규 명령의 `--help`와 전체 Python 구문 검사 성공.
- 새 시험은 일시적 제어기 알람 후 정상 복귀, 새 알람과 초기화의 경쟁, 실제 ROS 알람 토픽 수신, 제어기 모드에서 재개 거절·초기화 후 첫 선 재시작을 포함한다. ROS 시험 도메인은 실물과 분리된 99이다.
- 실제 드라이버의 읽기 전용 조회: 알람 발행자 발견, Tool/TCP·상태·힘 값 확인. 실물 이동·접촉·충돌 시험은 실행하지 않았다.
- JobManager·SQLite를 추가하지 않았으며 GitHub와 외부 Doosan 드라이버 소스도 수정하지 않았다.

## Tool/TCP 실행 기본값

전체 Launch는 `tool_name:=Tool_Weight`, `tcp_name:=GripperDA_v1`을 기본으로 사용한다. 이전 터미널에 `PenTool Weight` / `PenGripper` 환경변수가 남아 있어도 Launch가 드로잉 실행기에 전달하는 이름은 이 기본값이다. 다른 이름은 Launch 인자를 명시한 경우에만 사용한다. 단독 실행과 조회 명령은 위 `ART_TOOL_NAME`, `ART_TCP_NAME` 환경변수를 사용한다.

티치펜던트의 실제 선택값이 다르면 코드가 자동으로 전환하지 않고 실행을 거절한다. 등록 이름에 해당하는 무게·무게중심·TCP 좌표와 기존 보정의 일치 여부는 현장에서 확인한다.
