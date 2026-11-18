# 카메라·DrawingController 점검 결과

## 현재 판단

자동 시험이 통과했다고 해서 실제 M0609/RG2 드로잉이 완성된 것은 아닙니다. 현재 실행기는 확정 DrawingPlan을 두산 비동기 서비스에 연결하지만, 실제 장비의 보정·파지 확인·안전 설정이 없으면 실행을 거절합니다.

로컬에 있는 후보 프로필에는 안전 작업 공간, 이동 높이, 펜별 Z 오프셋, RG2 개폐 확인 DI가 비어 있습니다. 이 값을 추정하거나 `hardware_validated`만 바꿔 실행하도록 수정하지 않았습니다. 물리 실행·필압 검증은 이번 점검에서 하지 않았습니다.

## 사진 촬영을 허용하는 방법

같은 PC에서 `http://localhost:8000`으로 접속하고 주소창 왼쪽의 사이트 설정에서 카메라를 허용하세요. 권한을 바꾼 뒤 새로고침하고 **카메라 켜기**를 누릅니다. 운영체제의 카메라 차단과 다른 앱의 카메라 점유도 확인하세요.

촬영 버튼은 영상 프레임이 준비돼야 활성화됩니다. 작업 실행 중이거나 등록 결과가 미확정이면 새 사진 입력을 막는 기존 정책도 적용됩니다. 이 경우 현재 작업 상태를 확인해야 하며 저장 상태를 임의로 지워 회피하지 않습니다.

브라우저는 일반적으로 localhost 또는 신뢰된 HTTPS에서 카메라 접근을 허용합니다. 다른 PC의 `http://IP주소:8000`에서는 카메라 API가 차단될 수 있습니다. 코드가 브라우저의 권한을 대신 허용할 수는 없습니다. [MDN의 getUserMedia 설명](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)을 참고하세요.

이번 수정에서 다음 동작을 보완했습니다.

- 권한 차단·장치 없음·다른 앱 점유·보안 제한을 한국어로 구분해 안내합니다.
- 카메라를 여는 동안 중복 요청을 막고, 실제 영상 크기가 확인된 후 촬영을 허용합니다.
- 카메라 연결 종료를 감지해 촬영 버튼을 닫고 다시 켤 수 있게 합니다.
- 해상도 조건 거절 시 기본 영상 조건으로 다시 요청합니다.

실제 USB 카메라와 브라우저에서 촬영한 것은 아닙니다. 화면 동작은 QuickJS 시험으로 확인했습니다. 팀원은 localhost에서 발생한 카메라 문제를 별도로 해결했다고 전달했습니다.

## 모듈을 줄인 결과

ROS 실행 노드는 `drawing_controller` 하나입니다. 내부 파일을 하나로 합치는 것이 실행 조건은 아닙니다. 비동기 이동과 일시정지, 설정 검증을 한 파일에 몰아넣으면 수정 범위와 검증이 커지므로 다음 5개 구현 파일로 정리했습니다. `__init__.py`는 패키지 표시용입니다.

```text
art_drawing_controller/
├── drawing_node.py          # Action 수신, 프로필 선택, 실행·취소·결과
├── stroke_executor.py       # 종이 mm→로봇 좌표, 펜 교체, 획 실행
├── doosan_adapter.py        # 두산 서비스 계약, 실제 관측, 정지·재개·XYZ 제한
├── live_motion.py           # 같은 모션 보존, 제어 서비스, 심장박동
└── equipment_settings.py    # 프로필·계획·SHA 검사, 후보 변환, 읽기 전용 진단
```

아래 7개 파일은 기능을 옮긴 후 삭제했습니다. 안전 검사나 테스트를 삭제한 것은 아닙니다.

- `plan_loader.py`의 기능은 `equipment_settings.py`로 통합했습니다.
- `paper_transform.py`, `pen_controller.py`, `gripper_controller.py`는 `stroke_executor.py`로 통합했습니다.
- `motion_safety.py`, `doosan_motion_control.py`는 `doosan_adapter.py`로 통합했습니다.
- `live_control_server.py`는 `live_motion.py`로 통합했습니다.

기존 Python 내부 import 경로는 위 구조로 바뀌었습니다. 저장소 안의 테스트·Fake·문서도 함께 수정했습니다. 팀원이 별도로 작성한 코드에서 삭제한 모듈을 import한다면 새 위치로 바꿔야 합니다. ROS Action·서비스 이름과 필드는 그대로입니다.

## 로봇이 움직이지 않는 조건과 수정 내용

프로필 미설정·미검증, Tool/TCP 불일치, 드라이버 서비스 미발견, STANDBY가 아닌 시작 상태, 그리퍼 열림 미확인, 계획 방향·SHA 불일치는 실행 거절 원인입니다. 이 항목은 실행을 생략하는 빈 함수가 아닙니다.

- 프로필을 빠뜨린 경우 노드 시작 시 원인을 명확하게 출력합니다.
- `ART_EQUIPMENT_PROFILE` 외에 ROS 파라미터와 Launch 인자로도 프로필을 전달할 수 있습니다.
- 드라이버 서비스 접두 경로를 `service_prefix`로 지정할 수 있습니다. 기본은 `/dsr01/dsr_controller2`입니다.
- 서비스 발견 직후 준비 지연을 제한된 시간 동안 기다리고, 연결 오류에는 실패한 서비스 경로를 표시합니다.
- 실행 시작 시 로봇이 STANDBY 상태인지 추가로 검사합니다.
- 이동·펜 교체를 `pass` 처리하거나 가짜 성공으로 끝내는 실행 함수는 없습니다. 같은 목표 이동을 생략할 때도 실제 정지·현재 자세를 검사합니다.

기존 DO1/DO2 코드는 출력 명령입니다. 실제 파지·열림을 읽는 입력 정보는 제공되지 않았습니다. 현재 구현은 확인된 DI를 요구합니다. 장비가 DI 대신 다른 통신으로만 상태를 제공한다면 해당 상태 읽기를 추가로 연결해야 합니다. DO 출력값을 실제 파지 성공으로 바꾸어 보고하지 않습니다.

## 팀원 PC에서 먼저 실행할 읽기 전용 진단

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
source ros2_ws/install/setup.bash
ros2 run art_drawing_controller check_drawing_setup \
  --profile "$HOME/A4/data/equipment/reference_profile_unvalidated.json" \
  --driver
```

후보 파일을 사용한 위 명령은 누락 항목을 보여주고 종료 코드 2를 반환하는 것이 정상입니다. 실제 측정한 프로필이 있다면 그 경로로 바꾸세요. 이 명령은 모션·디지털 출력·Tool/TCP 변경을 요청하지 않습니다.

확인 항목은 패키지 import 경로, `ROS_DOMAIN_ID`, 프로필 누락값, 서비스 존재 여부입니다. 유효한 프로필과 서비스가 있을 때만 위치·속도·상태·Tool/TCP·입력을 읽어 시작 상태도 검사합니다. 진단 통과는 물리 경로의 충돌 검증이 아닙니다.

실물에서는 드라이버와 A4의 도메인·Discovery 설정을 맞춰야 합니다. `scripts/local_test_env.bash`는 격리된 Fake 시험용이므로 실물 설정에 그대로 적용하지 마세요.

A4 Launch는 두산 드라이버를 대신 실행하지 않습니다. 팀에서 사용하는 M0609용 드라이버를 먼저 실행해야 합니다. 설치된 드라이버 Launch의 기본 모델은 M0609가 아닐 수 있으므로 기존 검증한 장비 명령을 사용하세요. 실제 IP·포트·드라이버 모드를 추정하지 않았습니다.

## 빌드와 프로필 전달

```bash
cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
colcon build --symlink-install
source install/setup.bash
```

실물 설정 확인 후 전체 실행기에 프로필을 전달하는 형식은 다음과 같습니다. 아래 경로는 실제 검증한 JSON 경로로 바꿔야 합니다.

```bash
ros2 launch art_bringup art_system.launch.py \
  equipment_profile:=/실제/검증한/장비.json
```

프로필이 없는데 이 명령만으로 그림을 그릴 수 있다는 의미는 아닙니다. Fake 서버와 실물 Controller를 같은 Action 이름으로 동시에 실행하지 마세요.

## 실제 검증 결과

변경 전은 163개 통과, 1개 건너뜀이었습니다. 변경 후는 **171개 통과, 0개 실패, 1개 건너뜀**, 95.03초입니다. 건너뛴 항목은 별도 외부 서버와 `RUN_LIVE_KIOSK_TEST=1`이 필요한 선택 시험입니다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
source ros2_ws/install/setup.bash
source scripts/local_test_env.bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ROS_DOMAIN_ID=99 \
  /tmp/a4-review-venv/bin/python -m pytest tests -q --tb=short
```

생산용 DrawingNode·DoosanAdapter를 실제 설치된 `dsr_msgs2` 타입의 시험 전용 두산 서비스에 연결해 확정 계획 이동, DO 출력, 상태 관측, 펜 반납, 완료 피드백을 확인했습니다. 기존 중간 획 일시정지·재개·중단 시험과 JobManager 회귀 시험도 유지했습니다. 시험용 서비스가 물리 동작을 대신하므로 실물 드로잉 성공으로 보고하지 않습니다.

`colcon build --symlink-install --base-paths src`로 7개 패키지를 빌드했습니다. 읽기 전용 진단은 격리 도메인 98에서 후보 프로필의 누락값과 서비스 미발견을 정확히 보고했습니다. 이 결과를 팀원 장비의 실제 서비스 부재로 해석하면 안 됩니다.

로컬 ROS2·두산 메시지 import는 확인했지만 팀원 PC의 설치 상태는 제공되지 않았습니다. 제어기 GV02120100, RG2 V2와 현재 DRFL·드라이버 조합의 실물 호환성은 물리 시험이 남아 있습니다. 선화 가상환경 설치·모델 시험 기록은 [최초 통합 문서](REFERENCE_INTEGRATION_KR.md)에 있습니다.

이번 변경은 로컬에만 반영했습니다. GitHub 커밋·푸시는 실행하지 않았습니다.
