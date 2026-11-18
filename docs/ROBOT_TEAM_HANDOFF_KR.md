> 아래는 이전 버전의 기록입니다. 현재 버튼·SQLite·재개 정책은 [중단점 복구와 새 그림 시작](CHECKPOINT_RECOVERY_KR.md)을 우선 적용하세요. 초기화·외력 후 처음부터 그리기와 수동 허용 체크박스는 현재 사용하지 않습니다.

> 최신 점검과 실행 진단은 [로컬 코드 점검 결과](LOCAL_ROBOT_AUDIT_KR.md)를 먼저 확인하세요. 아래의 과거 시험 수는 해당 작업 당시 기록입니다.

# 실물 로봇 팀 인계와 현재 준비 범위

## 현재 판단

사진·영문 문구 입력 → 경로 자동 생성 → SVG 확인 → 사용자 그리기 승인 → JobManager 등록 → ExecuteDrawing 요청까지 구현되어 있다.
관리자 화면은 인증키 입력 없이 현재 작업을 조회하고 제어 명령을 전달한다.
이는 실제 장비로 그림을 완성했다는 의미가 아니다. 선화 품질은 사용자가 최종 SVG에서 확인해야 한다.

실물 구동 패키지의 이동 함수만 채운다고 바로 사용할 수 있는 상태는 아니다.
참고 코드의 실제 이동·펜 교체를 현재 실행기에 연결했다. 팀원은 장비 설정·캘리브레이션·상태 입력·중단·종료 처리를 실물에서 검증해야 한다.
최신 구현과 설정 조건은 [참고 코드 통합 문서](REFERENCE_INTEGRATION_KR.md)를 따른다.
필압 관련 기존 코드는 이번 작업에서 변경하지 않았다.

## 이번에 수정한 비로봇 부분

- 관리자 토큰 폼과 Bearer 검사·전송을 제거했다. 기존 ART_ADMIN_TOKEN 설정은 더 이상 인증 조건으로 사용하지 않는다.
- 교차 출처 요청 거절, 상태 유효 시간, 대상 작업 ID 검증, 중복 명령의 요청 ID 보존은 유지한다.
- 기본 웹 주소는 127.0.0.1이다. 인증키 없는 관리자 화면은 접근 가능한 사람 누구나 사용할 수 있다. 외부 접속 허용은 별도의 운영 결정이다.
- optimize_existing CLI의 기본 48획 제한을 없앴다. 명시적으로 --strokes를 지정하면 축약 기능을 사용할 수 있다.
- JobManager는 별도 Action Feedback 구독과 Goal UUID 비교로 완료 결과 뒤에 도착한 피드백을 처리한다.
  로컬 Jazzy rclpy의 ActionClient는 Result 처리 때 내부 피드백 콜백을 제거하므로 단순히 결과 처리를 늦추는 것만으로는 부족했다.
  피드백 큐 깊이는 1000이며, 결과가 앞서 도착하면 최대 2초 동안 관측된 완료 이벤트를 기다린다.
  실제 누락·불일치는 RECOVERY_REQUIRED(실제 상태 확인 필요)로 처리한다. 결과 수치로 체크포인트를 생성하지 않는다.

## 실제 로봇 패키지의 현재 구조

```text
ros2_ws/src/art_drawing_controller/
├── package.xml                         # ROS2·두산 메시지 의존성
├── setup.py                            # 실행 노드·프로필 변환·읽기 전용 진단 설치
├── setup.cfg                           # ROS2 실행 파일 설치 위치
├── resource/art_drawing_controller     # 패키지 등록
└── art_drawing_controller/
    ├── __init__.py                     # 패키지 표시
    ├── drawing_node.py                 # ExecuteDrawing Action 서버, 실행·취소 연결
    ├── stroke_executor.py              # 종이 좌표 변환, 펜 교체, 획 실행
    ├── doosan_adapter.py               # 두산 서비스, 상태 관측, 정지·재개, 범위 검사
    ├── live_motion.py                  # 동일 모션 보존, 제어 서비스, 심장박동
    └── equipment_settings.py           # 보정·계획·SHA 검사, 후보 변환, 설치·연결 진단
```

실행기는 저장된 평면·축·펜별 Z와 슬롯을 사용한다. 프로필이 없거나 검증이 빠진 경우 Goal을 거절한다.
후보 보정값은 승인된 실물 프로필이 아니다. Bringup YAML은 참고 설정이며 실제 장비에는 ART_EQUIPMENT_PROFILE의 JSON을 사용한다.
실제 6축 자세와 XYZ 범위를 검사하지만 충돌·관절 한계를 소프트웨어 시험으로 검증한 것은 아니다.

## 팀원이 확인하고 구현할 장비 정보

- 로봇: M0609, 통합 GV02120100, 메인 GF02120100. V2.12.1 계열로 해석하며 DRCF V2 연동을 기준으로 검증한다.
- 그리퍼: RG2 V2, 제품 번호 102012.
- 기존 제어: DSR_ROBOT2의 set_digital_output으로 제어기 DO1·DO2를 설정한다.
  제공된 release 함수의 최종 출력은 DO1=OFF, DO2=ON이다. 실제 열림·닫힘 배선과 상태 신호는 팀원이 확인한다.
- Compute Box·중간 장치·배선·닫기 코드·파지 완료 확인 방법은 미확인이다. 저장된 Modbus 설정만으로 운용 방식을 확정하지 않는다.
- 장비 프로필: TCP·하중·종이 원점과 축·펜 길이·펜 교체 위치·안전 접근 높이·속도·가속도·작업 공간을 검증한다.
- 버전: ROS2 드라이버 커밋·DRFL 라이브러리·제어기 버전·장비 프로필을 함께 기록하고 실행 전 호환성을 확인한다.
- 프로세스 종료·통신 단절 시에도 실제 로봇이 안전하게 멈추는 로컬 감시와 정지 절차가 필요하다.

## 팀원이 구현할 ExecuteDrawing 계약

담당 서버는 /art/execute_drawing이다. 기존 action 파일과 JobManager 검증 기준을 유지한다.

- Goal: job_id, plan_path, plan_sha256, start_stroke_id를 검증한다. 허용 루트와 SHA를 실행 직전에 다시 확인한다.
- Feedback: STARTED_LIVE → STROKE_STARTED → STROKE_COMPLETED 순서로 보고한다.
  STROKE_COMPLETED는 그 획의 실제 그리기 완료와 펜 이격을 확인한 후에만 보낸다.
- 장시간 획과 펜 교체 중에도 HEARTBEAT를 보내야 한다. 기본 감시 시간은 60초이며 심장박동은 완료 증거가 아니다.
- Result: 전체 완료는 SUCCEEDED/COMPLETED와 일치하는 연속 완료 획 수를 반환한다.
  중단 시에는 실제 정지와 안전 이격 확인 후 CANCELED/INTERRUPTED_SAFE를 반환한다.
- 관측이 불가능하면 pen_up_confirmed=true를 반환하지 않는다. 실패 또는 미확정 상태를 보고한다.
- 새로운 UUID의 실행을 이전 실행과 혼동하지 않도록 한다. 같은 Action 이름의 서버를 동시에 두 개 실행하지 않는다.

## 획 중간 일시정지·재개 구현

동일 Action·모션을 보존하는 서비스·세션·두산 제어 어댑터를 추가했다.
현재 계약과 팀원 연결 방법은 [획 중간 일시정지·재개 문서](CONTINUOUS_PAUSE_RESUME_KR.md)를 따른다.
PAUSE는 더 이상 Action 취소가 아니며 RESUME도 새 Goal을 보내지 않는다.
프로필 미설정 시 Goal 거절을 유지한다. 장비 보정·그리퍼 상태 입력과 전체 실제 경로는 실물 검증 대상이다.
아래 134개 통과 기록은 이 기능 추가 전의 검증 기록이다.

## 남은 운영 검증

RECOVERY_REQUIRED(복구 필요)와 UNKNOWN_PREPARATION(준비 결과 미확정)은 운영자가 실제 상태를 확인해야 한다.
현재 자동 복구·운영자 안전 해제 화면은 제공하지 않는다. 새 DB 생성은 시험 격리 방법이며 운영 복구 방법이 아니다.
제공 사진 외의 선화 품질, 종이 접촉, 파지·교체, TCP·보정, 실물 중단·종료는 별도 검증 대상이다.
Fake 성공은 이러한 항목의 성공을 의미하지 않는다.

## 이번 실행 검증 기록

변경 전에는 기본 Python 환경에서 120개 통과, 2개 건너뜀을 확인했다.
건너뛴 항목은 QuickJS 미설치로 인한 프런트엔드 시험 모듈과 별도 실행 서버를 요구하는 선택 시험이었다.
pytest 자동 로드 ROS launch 플러그인이 수집 중 importorskip을 전체 수집 중단으로 처리하는 현상이 있어
명령에서 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1을 사용했다. 시험을 삭제하거나 성공으로 바꾸지 않았다.

QuickJS는 저장소 밖 /tmp/a4-review-venv에 설치했고 시스템 ROS2 패키지를 공유했다.
변경 후 실행 명령은 다음과 같다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ROS_DOMAIN_ID=97 \
  /tmp/a4-review-venv/bin/python -m pytest tests -q -rs
```

결과는 134개 통과, 0개 실패, 1개 건너뜀이다.
건너뛴 것은 RUN_LIVE_KIOSK_TEST=1과 별도 실행 서버를 요구하는 외부 HTTP 응답성 시험이다.
ASGI 사진 처리 중 응답성, QuickJS 화면 동작, 실제 ROS2 통합은 별도 테스트에서 실행했다.

신규 검증은 60개 독립 획의 CLI 기본 보존, Result 선행 도착과 피드백 누락,
획당 0.001초·0.01초 Fake의 실제 DDS 통신과 60개 체크포인트 보존이다.
Fake의 시간을 늘려 문제를 피하지 않았다.
별도 Feedback 구독은 RELIABLE, KEEP_LAST 깊이 1000이다. 실물 서버도 호환되는 QoS를 제공해야 한다.
유한 큐와 2초 대기 범위를 넘는 누락·지연까지 정상 완료를 보장하는 것은 아니다. 그 경우 안전하게 복구 필요 상태로 처리한다.

빌드는 다음 명령으로 7개 패키지가 모두 완료되었다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
colcon --log-base /tmp/a4-colcon-log build --symlink-install \
  --base-paths ros2_ws/src --build-base ros2_ws/build --install-base ros2_ws/install
```

실제 실행한 빌드는 같은 build 옵션을 사용했고 --log-base를 생략했다.
생성된 루트 log 디렉터리는 시험 후 저장소 밖 /tmp/a4-build-logs-*로 이동했다.

실제 저장 사진 data/reference/lineart/samples/person1.jpg와 Hi 문구로
CV 선화 → 72개 획 계획 → SVG → SHA 검사 → 실제 ProductionEngine 등록(QUEUED)도 실행했다.
결과는 /tmp/a4-real-photo-check-54e4god5에 있다. 실제 사진을 사용했지만 그림의 품질 합격이나 로봇 이동 검증을 뜻하지 않는다.
실물 로봇·RG2 명령과 참고 정지 시험 프로그램은 실행하지 않았다.
