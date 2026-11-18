> 이 폴더는 Tool/TCP 수정 직후 복원본에 중단점 복구와 자동 이전 작업 정리를 추가한 로컬 작업본입니다. [복원 근거·검증·한계](docs/RESTORE_TOOL_TCP_VERSION_KR.md)를 먼저 확인하세요. 실물 좌표 문제는 별도 검증이 필요합니다.

# A4 퍼즐 드로잉 로봇

사진과 영문 문구를 입력하면 가로 A4 경로를 만들고, UI의 **그리기** 버튼으로 실행합니다. 같은 화면에서 일시정지·재개·정지를 조작합니다. `/admin`은 통합 UI로 이동합니다.

현재 구조에는 JobManager가 없습니다. 작업 파일은 디렉터리에 저장하고 정상 주행 샘플은 RAM에 관리합니다. 중단·외력 사건의 복귀점만 SQLite에 보존합니다. 최신 팀 인계 자료는 [중단점 복구와 새 그림 시작](docs/CHECKPOINT_RECOVERY_KR.md)입니다.

- `art_kiosk`: 사진 촬영·첨부, 문구, 묘사 슬라이더와 길이 진행률, 제어 버튼.
- `art_kiosk_bridge`: HTTP와 ROS 서비스·액션·상태 토픽 연결.
- `art_artwork_pipeline`: 선화·경로·영문 필기체 생성과 제공된 `draw_image_standalone.py` 기반 실행.
- `art_interfaces`: 준비 액션, 실행 요청·제어 서비스, 상태 메시지.
- `art_bringup`: 위 노드들의 통합 Launch.

[변경 내용·실행 방법·실물 준비 조건·테스트](docs/UNIFIED_UI_CONTROL_KR.md)를 먼저 확인하세요. 보정 파일 3개는 다운로드에서 실행 경로로 복사했습니다. 최신 보호 모드와 현재 장비 상태는 [실물 실행 준비 안내](docs/REAL_ROBOT_NEXT_STEPS_KR.md)를 확인하세요. 실물 드로잉 시험은 아직 수행하지 않았습니다.

```bash
cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
colcon build --symlink-install
source install/setup.bash
```

일시정지·정지·외력 후 **재개**는 저장한 마지막 정상 계획점부터 같은 그림을 이어 그립니다. 선분 일부는 빈틈 방지를 위해 겹쳐 그릴 수 있습니다. **그리기**는 이전 그림의 정지·정리를 자동 확인한 뒤 새 도안을 시작합니다. 별도의 허용 체크박스는 없습니다. 이전 체크포인트 이력은 보존합니다.

외력 임시값과 수정 위치, 재시작 복구 조건은 [중단점 복구 안내](docs/CHECKPOINT_RECOVERY_KR.md)를 확인하세요. 실물 동작·임계값은 검증하지 않았습니다. [직접 시험 순서](docs/HMI_MANUAL_TEST_KR.md)를 따라 확인하세요.

전체 Launch의 기본 Tool/TCP는 기존 설정인 `Tool_Weight` / `GripperDA_v1`입니다. 티치펜던트에서도 같은 설정을 선택해야 합니다.
