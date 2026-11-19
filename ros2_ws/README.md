# A4 ROS2 워크스페이스

최신 사용자 자동 미리보기·그리기 및 관리자 자동 작업 조회는 [HMI 직접 시험](../docs/HMI_MANUAL_TEST_KR.md)을 참고하세요.

7개 기능 패키지의 실제 구현은 `src/`에 있습니다. `build/`, `install/`, `log/`는 생성물입니다.
전체 빌드·노드별 실행·테스트·검증 제한은 [통합 안내](../docs/ROS2_PACKAGE_REFACTOR_KR.md)를 참고하세요.

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
ros2 launch art_bringup art_system.launch.py
```

Kiosk 사진·문구 → Bridge → PrepareArtwork → 사용자 경로 확인·그리기 승인 → JobManager → ExecuteDrawing 순서입니다.
미리보기 생성은 로봇 실행 승인이 아닙니다. 실물 Controller는 검증 전 모든 Goal을 거절합니다.
Fake Controller는 테스트 전용이며 거절 전용 Controller와 같은 Action 이름으로 동시에 실행하지 않습니다.
기존 JobManager의 SHA·SQLite·체크포인트·RECOVERY_REQUIRED 규칙을 유지합니다.
