# art_kiosk

현재 사용자·관리자 화면은 [자동 HMI 시험 안내](../../../docs/HMI_MANUAL_TEST_KR.md)의 흐름을 사용합니다.
사진·영문 문구를 입력하면 경로가 자동 생성되고 사용자 그리기 클릭으로 등록합니다.
관리자는 ID 입력 없이 현재 작업을 조회하고 일시정지·재개·중단을 수행합니다.

`art_kiosk/server.py`: FastAPI 사진 입력·선화 확인·관리자 계획 생성 요청·정적 리소스 제공.
`hmi_api.py`: 관리자 동일 출처 검사, 상태 신선도 검사, 작업 등록·PAUSE/RESUME/CANCEL 중계.
`preprocess.py`: 기존 이미지 정규화. `static/`: 사용자 화면과 관리자 HMI.

```bash
source /opt/ros/jazzy/setup.bash
source ~/A4/ros2_ws/install/setup.bash
ros2 run art_kiosk kiosk
```

Pipeline과 Bridge를 함께 실행해야 사진 변환이 가능합니다. 기본 엔진은 CV입니다.
`ART_JOB_PLAN_ROOT`는 모든 노드에서 같아야 합니다. 관리자 인증키 설정은 필요하지 않습니다.
`workflow.py`는 현재 작업 기록·파일 잠금·미리보기 티켓·중복 등록·응답 유실을 처리합니다.
사용자 API는 `/api/kiosk/prepare`, `/api/kiosk/preview`, `/api/kiosk/draw`, `/api/kiosk/current`입니다.
관리자 API는 동일 출처의 `/api/admin/current`, `/api/admin/current/control`과 미디어 조회입니다.
구형 사진·확인·관리자 등록 API는 호환용이며 새 화면에서 사용하지 않습니다.
새 워크플로 기록이 있으면 구형 관리자 등록 API를 통한 우회 등록을 거절합니다.
설치 시 정적 파일이 포함되며 데이터는 소스 밖 작업별 디렉터리에 저장합니다.

[전체 API 변경·실행·테스트 안내](../../../docs/ROS2_PACKAGE_REFACTOR_KR.md)
