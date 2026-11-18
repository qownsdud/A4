# 중단점 복구 변경 검증 결과

2026-11-18 로컬 A4에서 실행했습니다. GitHub에는 반영하지 않았습니다. 작업 전 복원본의 기준 결과는 129개 통과였으며, 이번 최종 회귀 결과는 **141개 통과, 실패 0개, 건너뜀 0개**입니다.

## 실행한 명령

실물과 분리한 ROS 도메인 99에서 전체 회귀를 실행했습니다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/local_setup.bash
source ros2_ws/install/local_setup.bash
source scripts/local_test_env.bash
PYTHONPATH="/tmp/a4-hmi-js-check:$PYTHONPATH" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 -m pytest -c /dev/null --rootdir=. -o cache_dir=/tmp/a4-new-tests tests -q -rs
```

최종 결과는 `141 passed in 57.80s`입니다. 로그는 `/tmp/a4-new-tests.log`에 있습니다. 시험용 SDK·프로세스와 실제 ROS 메시지 타입을 연결한 결과이며 실제 로봇을 움직이지 않았습니다.

```bash
cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/local_setup.bash
colcon build --symlink-install
```

5개 패키지가 모두 빌드됐습니다. 로그는 `/tmp/a4-checkpoint-build.log`에 있습니다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/local_setup.bash
source ros2_ws/install/local_setup.bash
python3 -m compileall -q ros2_ws/src tests
ros2 interface show art_interfaces/srv/ControlJob
python3 -c 'from art_artwork_pipeline.recovery_store import CheckpointStore; from art_artwork_pipeline.recovery_plan import verify_checkpoint; print("installed recovery imports OK")'
```

구문 검사, 생성된 서비스 설명과 설치된 복구 모듈 import를 확인했습니다. 서비스 필드는 바꾸지 않았고 명령 문자열의 의미를 확장했습니다.

## 통신 외에 확인한 동작

- 실제 `run_robot_drawing()` 본문을 모의 SDK로 실행하여 획 중간 일시정지·정지·외력 이후 첫 획부터 다시 시작하지 않는지 확인했습니다.
- 같은 함수에서 기존 제어 객체를 종료하고 디스크 중단점을 읽은 새 제어 객체로 이어 그리기를 확인했습니다. 원본 DrawingPlan 해시는 유지됐습니다.
- 중단 후 실제 좌표가 밀려도 복귀 목표가 원래 계획점으로 유지되는지 검사했습니다.
- 정상 샘플 250개를 추가해도 RAM에는 최근 100개만 남고 DB 파일을 만들지 않는지 확인했습니다.
- 사건 중복 저장 방지, WAL, 중단점 이력 보존, 계획·보정 변경 거절을 검사했습니다.
- 일시정지 후 홈 도달 기록을 디스크에서 다시 읽어 관절 왕복 경로와 계획 복귀점을 사용하는지 확인했습니다.
- DB가 손상됐을 때 새 실물 실행 요청을 거절하는지 확인했습니다.
- UI의 별도 허용 체크박스 제거, 기존 정리가 거절됐을 때 새 등록 차단, 정리 성공 후 새 등록, 외력 해소 후 같은 도안 정리 재시도를 검사했습니다.
- 기존 선화·경로·파일 격리·UI·Bridge·ROS 회귀 항목을 유지했습니다. 예전의 초기화·첫 선 재시작 기대값은 새 요구사항에 맞게 변경했습니다.

## 미검증 사항

실물 M0609·RG2의 이동·정지 응답·그리퍼 파지, 실제 종이 배치와 Tool/TCP 수치, 필압, 정상 힘 범위, 임시 외력 값의 감도, 잉크 번짐·부분 재도색 품질은 검증하지 않았습니다. DL 모델 추론과 모든 전원 차단 시점의 정확한 복원도 이번 결과에 포함되지 않습니다.

현장 순서는 [직접 시험 안내](HMI_MANUAL_TEST_KR.md), 정책·설정 위치는 [팀 인계 문서](CHECKPOINT_RECOVERY_KR.md)를 확인하세요. 과거 `RESTORE_FILES_SHA256.json`은 복원 시점의 기준 기록이며 최신 변경 목록은 `LOCAL_CHECKPOINT_CHANGES.json`입니다.
