> 아래는 이전 버전의 기록입니다. 현재 버튼·SQLite·재개 정책은 [중단점 복구와 새 그림 시작](CHECKPOINT_RECOVERY_KR.md)을 우선 적용하세요. 초기화·외력 후 처음부터 그리기와 수동 허용 체크박스는 현재 사용하지 않습니다.

> 모듈 통합 후의 파일 구조와 진단 명령은 [로컬 코드 점검 결과](LOCAL_ROBOT_AUDIT_KR.md)를 확인하세요.

# 획 중간 일시정지와 같은 경로 재개

## 바뀐 동작

HMI의 일시정지는 진행 중인 ExecuteDrawing Action을 취소하지 않는다.
Controller의 같은 실행 UUID와 로봇 제어기 내부 경로를 유지하며 MovePause로 멈춘다.
재개는 MoveResume로 그 모션의 남은 구간을 이어간다. 획 시작점으로 돌아가거나 다음 획을 건너뛰지 않는다.
완료 획 수와 진행률은 일시정지만으로 증가하지 않는다.

```text
HMI 일시정지
→ Kiosk → Bridge → ControlJob(PAUSE)
→ JobManager PAUSING
→ ControlDrawing(PAUSE, 동일 실행 UUID)
→ 모션 생산 게이트 닫기 → 두산 MovePause → 정지 관측
→ JobManager PAUSED

HMI 재개
→ Kiosk → Bridge → ControlJob(RESUME)
→ SHA 확인 → JobManager RESUMING
→ ControlDrawing(RESUME, 동일 실행 UUID)
→ 위치·상태 확인 → 두산 MoveResume → 실제 움직임/동일 목표 도달 확인
→ 모션 생산 게이트 열기 → JobManager DRAWING
```

작업중단은 Action Cancel을 사용한다. STOPPING 상태에서 실제 모션 정지와 펜 이격 확인 후에만
CANCELED/INTERRUPTED_SAFE 결과를 보내고 STOPPED로 확정한다.
일시정지와 달리 중단한 모션은 자동 재개하지 않는다.

## 코드별 책임

- art_interfaces/srv/ControlDrawing.srv는 활성 Action의 job_id·execution_id·command·request_id를 받는다.
  PAUSE와 RESUME만 제공하며 응답은 실제 확인된 PAUSED 또는 DRAWING이다.
  기존 CreateJob·ControlJob·ExecuteDrawing의 필드와 /art/execute_drawing 이름은 유지한다.
- ExecuteDrawing의 STARTED_LIVE 이벤트는 동일 모션 일시정지 지원 선언이다.
  STARTED만 보내는 구형 Controller에 중간 획 PAUSE를 요청하면 운영 ROS 노드는 거절한다.
- art_job_manager/production_engine.py는 live_execution과 RESUMING 상태를 관리한다.
  live 실행의 uncertain_stroke는 완료하지 않은 진행 중 획이므로 그대로 보존한다.
  기존 Action 종료 후 남은 미확정 획과 달리 동일 실행에서만 재개할 수 있다.
- job_repository.py는 기존 SQLite DB에 live_execution 열을 추가한다. DB·작업 이력을 삭제하지 않는다.
  재시작하면 PAUSED와 RESUMING도 RECOVERY_REQUIRED로 바꿔 자동 재개를 막는다.
- job_manager_node.py는 활성 Goal UUID를 ControlDrawing 요청에 묶는다.
  PAUSE/RESUME는 별도 서비스로, CANCEL만 Action 취소로 전달한다.
  기능 확인·명령 응답이 5초 안에 확정되지 않거나 통신이 실패하면 복구 필요로 처리하고 취소를 시도한다.
  종료할 때도 실행 중 작업을 복구 필요로 기록한다. 종료 시 취소 전송은 물리 정지 보장이 아니다.
- live_motion.py의 LiveMotionSession은 동일 이동 제출·진행 상태를 유지한다.
  잠긴 동안 새 모션 제출과 모션 완료 확정을 차단하며 중복 명령·UUID 불일치·취소 경합을 검사한다.
- live_motion.py의 LiveControlServer는 /art/control_drawing 서비스와 HEARTBEAT를 제공한다.
  활성 세션에만 명령을 전달한다. 세션이 없으면 NO_ACTIVE_EXECUTION으로 거절한다.
- doosan_adapter.py의 DoosanMotionControl은 두산 MovePause·MoveResume·MoveStop·CheckMotion·GetRobotState·GetCurrentPosx·GetCurrentVelx를 호출한다.
  서비스 수락만으로 정지·재개를 확정하지 않는다. 위치·속도·상태와 동일 목표 도달을 확인한다.
- drawing_node.py는 동시 콜백·Action Cancel과 확정 계획 실행을 연결한다.
  검증 프로필이 없으면 실행을 거절한다. 장비 보정·파지 상태 입력·실제 안전 이격은 실물 검증 대상이다.
- 사용자 화면은 RESUMING을 “멈춘 위치에서 재개 확인 중”으로 표시한다.
  관리자 화면은 이 상태에서도 작업중단 버튼을 사용할 수 있다.

## 로봇 구동 담당자의 연결 방법

현재 경로 실행기는 stroke_executor.py에 구현되어 있다. 펜 교체 기능도 같은 파일에 통합했다.
equipment_settings.py는 실제 프로필과 계획을 검사하며, 검증되지 않은 보정값으로 실행하지 않는다.
필압 관련 코드는 변경하지 않았다.

활성 경로 실행기는 다음 순서를 반드시 적용해야 한다.

1. 계획 SHA·장비 프로필·TCP·종이 보정·파지·작업 공간을 검사한다.
2. DoosanMotionControl을 생성한다. ready, stop_and_lift, motion_complete는 필수 실제 관측 함수다.
   임의로 True를 반환하는 함수로 연결하면 안 된다.
3. Goal UUID를 소문자 hex 문자열로 변환해 LiveMotionSession에 전달하고 LiveControlServer.bind로 등록한다.
4. 준비된 실행에서 STARTED_LIVE를 보낸다.
5. 비동기 이동 제출은 session.submit_motion을 통해 직렬화한다.
   submit에 전달하는 함수는 모션 제출 직후 반환해야 하며 이동 완료까지 동기 대기하면 안 된다.
6. 실제 동일 목표 도달을 확인한 뒤, RUNNING 상태에서만 session.complete_motion을 호출한다.
   일시정지 중 CheckMotion=IDLE이나 이동 서비스 응답만으로 목표 도달을 처리하면 안 된다.
7. 전체 획을 실제로 그리고 펜 이격을 확인한 뒤에만 STROKE_COMPLETED를 보낸다.
8. is_cancel_requested는 일시정지 대기 중에도 검사한다. session.cancel이 실제 정지·이격을 확인한 경우에만
   INTERRUPTED_SAFE/pen_up_confirmed=true를 반환한다. 실패하면 FAILED와 확인되지 않은 이격 상태를 보고한다.
9. session.finish가 성공해야 정상 완료한다. 마지막 완료와 PAUSE가 경합해도 일시정지를 건너뛰면 안 된다.
10. 종료 경로에서 LiveControlServer.unbind를 호출한다.

모션 worker·서비스·드라이버 응답을 동시에 처리할 MultiThreadedExecutor와 콜백 그룹이 필요하다.
기본 drawing_node는 4개 스레드 구조를 사용한다. 블로킹 worker 수를 늘리면 그에 맞춰 설계를 다시 확인한다.
두산 드라이버가 동기 이동 서비스 처리 때문에 Pause 서비스를 막지 않도록 비동기 이동을 사용해야 한다.

ready는 실행 시작 시 승인한 장비 프로필·TCP·펜 상태가 유지되는지도 확인해야 한다.
motion_complete는 현재 활성 모션의 실제 목표 도달을 확인한다. 다른 획이나 전체 작업 완료 여부가 아니다.
stop_and_lift는 실제 정지 후 장비에 맞는 안전 이격을 수행하고 관측한다. 그리퍼 해제와 혼동하면 안 된다.
Controller에는 Manager 종료·통신 단절 시 동작을 제한하는 장비 측 감시도 필요하다.

## 경계와 거절 조건

- 정지 위치에서 펜을 자동으로 들어 올리지 않는다. 경로를 끊지 않고 같은 모션을 보존하기 위해서다.
  PAUSED는 비상정지나 작업 공간 진입 허가를 뜻하지 않으며 pen_up_confirmed도 아니다.
- 펜을 종이에 대고 멈추면 번짐·잉크 자국이 생길 수 있다. 경로 연속성과 실제 품질은 실물로 검증한다.
- 기본 관측값은 3회 정지 샘플, 선속도·각속도 각 성분 절댓값 0.01 이하,
  위치 변위 0.1 mm 이하, 자세 성분 변위 0.1도 이하다. 실제 장비 검증에 맞춰 조정해야 한다.
  이 값들은 인증된 안전 한계가 아니다. 기본 명령 확인 제한은 3초다.
- 자세는 같은 오일러 표현만 허용한다. 다른 동등 표현을 자동 변환하지 않고 거절한다.
- 비상 정지·보호 정지·전원 차단·수동 이동·제어권 변경·드라이버 재시작 등으로 경로 문맥이 사라지면
  새 Goal로 추측해 이어 그리지 않는다. 같은 위치여도 경로 보존을 확인하지 못하면 실패한다.
- 완료되지 않은 획을 DB의 완료 획으로 승격하거나 부분 경로를 임의로 보간하지 않는다.
- 구형 안전 중단·체크포인트 복구 단위 테스트는 유지한다. 구형 엔진의 새 Goal 재개와 live 모드를 혼합하지 않는다.

## 공식 동작 근거와 참고 코드

참고 파일 /home/yongsoo/ws_cobot_pjt/ws_dsr/src/rokey1/rokey1/motion_pause_resume_stop.py의
서비스 이름과 비동기 호출 방식을 확인했다. 파일의 고정 이동 좌표·자동 시험 순서는 가져오거나 실행하지 않았다.

두산 공식 설명에 따르면 MovePause는 활성 모션을 보존하고 MoveResume는 그 모션을 이어간다.
Stop으로 종료한 모션은 같은 방식으로 재개할 수 없다.
현재 로봇의 상세 펌웨어에서 동일 동작이 나오는지는 실물 시험 대상이다.

- [공식 move_pause 설명](https://doosanrobotics.github.io/doosan-robotics-api-manual/GL013305/mode/common/motion_execution/move_pause.html)
- [공식 move_resume 설명](https://doosanrobotics.github.io/doosan-robotics-api-manual/GL013305/mode/common/motion_execution/move_resume.html)
- [Stop과 Resume의 구분](https://doosanrobotics.github.io/doosan-robotics-api-manual/GL013304/mode/manual/jogging_motion_control/move_resume.html)

## 자동 검증과 실행

실물과 수동 Fake 시험에서 분리한 ROS_DOMAIN_ID=99를 사용한다. Fake와 실제 Controller를 같은 도메인·Action 이름으로 함께 실행하지 않는다.
로컬 두산 메시지 타입까지 검증하려면 vendor overlay를 먼저 읽는다. 이것만으로 로봇 드라이버가 실행되지는 않는다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source /home/yongsoo/ws_cobot_pjt/ws_dsr/install/setup.bash
source ros2_ws/install/setup.bash
source scripts/local_test_env.bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ROS_DOMAIN_ID=99 \
  /tmp/a4-review-venv/bin/python -m pytest tests -q -rs
```

QuickJS 시험 환경을 새로 준비해야 한다면 다음을 실행한다.

```bash
python3 -m venv --system-site-packages /tmp/a4-review-venv
/tmp/a4-review-venv/bin/pip install quickjs==1.19.4
```

tests/integration/test_hmi_mid_stroke_resume.py는 HMI HTTP → 실제 Bridge·Manager·ROS Action·서비스를 연결한다.
한 획의 중간에서 두 번 멈추고 재개해도 Action Goal은 한 번만 생성되고,
경로 샘플이 빠지거나 중복되지 않는지 확인한다. 정지 중 작업중단과 드라이버 실패도 검사한다.
tests/integration/test_doosan_motion_services.py는 실제 dsr_msgs2 타입으로 시험용 두산 서비스에 연결한다.
이 시험용 서비스가 실제 M0609의 정지 응답이나 종이 접촉을 재현하는 것은 아니다.

## 최종 실행 결과

전체 시험 결과는 153개 통과, 실패 0개, 건너뜀 1개이며 실행 시간은 32.14초다.
건너뛴 것은 별도 서버와 RUN_LIVE_KIOSK_TEST=1을 요구하는 선택 HTTP 응답성 시험이다.
두산 overlay를 읽었으므로 dsr_msgs2 서비스 타입 시험은 건너뛰지 않고 실행했다.
Python 94개 파일의 구문 검사와 ros2 interface show art_interfaces/srv/ControlDrawing도 통과했다.

ROS2 빌드는 7개 패키지가 모두 완료되었다. 실행 명령은 다음과 같다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source /home/yongsoo/ws_cobot_pjt/ws_dsr/install/setup.bash
colcon --log-base /tmp/a4-final-live-control-build-log build --symlink-install \
  --base-paths ros2_ws/src --build-base ros2_ws/build --install-base ros2_ws/install
```

실물 M0609·RG2, 실제 종이 접촉, 잉크 번짐·획 연속성의 품질은 이번에 검증하지 않았다.
실제 경로 실행기와 검증 콜백을 연결하기 전에는 기본 Controller의 Goal 거절을 해제하지 않는다.
ready는 장비 설정뿐 아니라 제어권·드라이버 연결 세대·외부 모션 개입 여부를 확인해야 한다.
검증 콜백은 제한 시간 내에 반환하도록 구현하며, 실패하면 자동 재시도·경로 추측으로 복구하지 않는다.
