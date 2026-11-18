# art_kiosk

사진 촬영·첨부, 영문 문구, 묘사 슬라이더, 경로 미리보기와 실행 제어를 하나의 UI에서 제공합니다. `/admin`은 통합 UI로 이동합니다.

- `server.py`: FastAPI API와 정적 리소스 제공.
- `workflow.py`: 현재 사진·계획·실행 요청 연결과 상태 불명 시 새 작업 차단.
- `hmi_api.py`: 동일 출처·상태 신선도 확인과 Bridge 요청 중계.
- `preprocess.py`: 입력 이미지 정규화.
- `static/app.js`: 길이 진행률과 일시정지·재개·초기화, 외력 경고 표시.

```bash
source /opt/ros/jazzy/setup.bash
source ~/A4/ros2_ws/install/setup.bash
ros2 run art_kiosk kiosk
```

기본 주소는 `http://localhost:8000`입니다. `ART_JOB_PLAN_ROOT`는 모든 노드에서 같아야 합니다. 관리자 인증키는 사용하지 않으며 동일 출처 정책을 유지합니다.

[통합 실행·설정·시험 안내](../../../docs/UNIFIED_UI_CONTROL_KR.md)
