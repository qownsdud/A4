# 통합 UI 직접 시험

현재 정책과 데이터 구조는 [중단점 복구와 새 그림 시작](CHECKPOINT_RECOVERY_KR.md)을 먼저 확인하세요. JobManager는 없으며 예외 중단점만 SQLite에 저장합니다. 실물 검증은 이번 자체 시험에 포함하지 않았습니다.

## 빌드와 실행

로봇이 정지한 상태에서 기존 A4 노드만 종료하고 빌드합니다. 드라이버를 중복 실행하지 않습니다.

```bash
cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
colcon build --symlink-install
source install/setup.bash
```

별도 터미널에서 현재 장비에 사용하던 드라이버를 연결합니다. IP·도메인은 현장 설정을 사용하세요. 다음 예의 도메인 40도 드라이버 설정과 같을 때만 사용합니다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
source ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=40
export ART_JOB_PLAN_ROOT="$HOME/A4/data/jobs"
export ART_MOTION_CONTROL_CONFIG="$HOME/.ros/a4_motion_control.json"
export ART_TOOL_NAME='Tool_Weight'
export ART_TCP_NAME='GripperDA_v1'
export ART_LINEART_METHOD=cv
ros2 launch art_bringup art_system.launch.py virtual:=false dry_run:=false
```

위 실행은 실물 연결 모드입니다. 보정·Tool/TCP·파지 상태·홈 왕복과 보호 설정을 확인한 뒤에만 그리기를 누르세요. 기존 접촉 측정 함수는 유지되어 첫 실행에 실제 접촉 이동이 있습니다. `skip_cal`이 모든 접촉 측정을 생략하는 것은 아닙니다. 화면만 볼 때는 그리기를 누르지 마세요.

`http://localhost:8000`을 열고 `Ctrl+Shift+R`로 강력 새로고침합니다. 설정 변경 후에는 A4 노드를 재시작합니다. `dry_run:=true`는 상태 기록을 삭제하거나 실물 검증을 대신하는 옵션이 아닙니다.

## 확인할 순서

1. 간단한 사진과 짧은 영문 문구로 미리보기를 만듭니다. 이전 작업이 있어도 입력·도안 생성은 가능해야 합니다.
2. 작업 공간을 비우고 그리기를 누릅니다. 별도 허용 체크박스 없이 기존 실행을 정리한 뒤 새 그림이 시작되는지 확인합니다. 정지·정리 실패가 표시되면 원인을 해결하고 진행합니다.
3. 먼저 짧은 경로로 좌표·펜과 실제 그리기 위치를 확인합니다. 잘못된 위치라면 즉시 현장 정지 절차를 사용합니다.
4. 긴 획의 중간에서 일시정지를 누릅니다. 정지점 저장·상승·홈 도착 뒤 재개를 누릅니다. 마지막 정상 계획점으로 돌아가 남은 선을 이어야 합니다. 선분 일부는 겹쳐 그릴 수 있지만 첫 획부터 다시 시작하면 안 됩니다.
5. 다음에는 획 중간에서 **정지 · 이어그리기 보존**을 누르고 재개합니다. 진행 회차와 완료된 획은 유지되어야 합니다.
6. 중단점이 저장된 상태에서 정상 종료 후 A4만 다시 실행합니다. 같은 종이·펜·보정 상태를 확인하고 재개했을 때 첫 펜 개폐·기준면 재측정 없이 이어지는지 확인합니다. 노드를 강제 종료하거나 전원을 끄는 시험은 별도 준비 없이 수행하지 않습니다.
7. 이전 그림을 중단한 상태에서 새 도안을 만들고 그리기를 누릅니다. 기존 펜 정리·실제 정지 후 새 그림을 시작하며 옛 체크포인트 이력은 남아야 합니다.

외력 검증은 로봇 담당자가 정한 별도 절차로 진행하세요. 사람의 몸이나 손으로 움직이는 로봇을 밀어 시험하지 않습니다. 소프트웨어에서는 기준 초과 → 실제 정지 관측 → 중단점 저장 → 경고 → 원인 해소 후 재개를 검사합니다. 제어기 보호 정지는 티치펜던트의 정상 복구 절차가 필요합니다.

## 소프트웨어 자체 시험 재실행

아래 환경은 **실물과 분리된 시험 터미널**에서만 사용합니다. 실물 Launch 터미널에 적용하지 마세요.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
source ros2_ws/install/setup.bash
source scripts/local_test_env.bash
PYTHONPATH="/tmp/a4-hmi-js-check:$PYTHONPATH" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 -m pytest -c /dev/null --rootdir=. -o cache_dir=/tmp/a4-new-tests tests -q -rs
```

`/tmp/a4-hmi-js-check`는 이 PC의 QuickJS 설치 위치입니다. 팀원 PC에서는 시험용 Python 환경에 `quickjs`를 설치하고 그 환경으로 실행하세요. 없으면 JS 시험이 건너뛰므로 결과를 확인합니다.

정상 주행의 SQLite 무기록, 링 버퍼 제한, 사건 중복 저장 방지, 원본 해시 검증, 실측 충돌 좌표와 복귀점 분리, 중간 선분 재개, 노드 재시작, UI·Bridge·ROS·시험 프로세스 왕복을 검증합니다. 실제 드로잉 함수도 모의 SDK로 실행합니다. 실물 이동·안전 정지 거리·정상 외력 범위·잉크 품질과 DL 추론은 별도 확인 대상입니다.
