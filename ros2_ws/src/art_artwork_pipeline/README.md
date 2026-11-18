# art_artwork_pipeline

`lineart/`: OpenCV·DL·MediaPipe 얼굴/Canny 혼합 선화. `path_planner/`: Stroke 추출·단순화·A4 mm 변환·검증·최적화·SVG.
`puzzle/colors.py`: 재현 가능한 4×4 논리 펜 6/5/5 배정.
`calligraphy/`: 영문 대소문자·공백의 2D 필기체. `pipeline_runner.py`: 파일 격리와 단계 실행.
`pipeline_node.py`: `/art/prepare_artwork` Action, 단일 처리 슬롯과 단계 사이 취소.

```bash
source /opt/ros/jazzy/setup.bash
source ~/A4/ros2_ws/install/setup.bash
ros2 run art_artwork_pipeline artwork_pipeline
python3 -m art_artwork_pipeline.lineart.cli --help
python3 -m art_artwork_pipeline.path_planner.cli --help
```

확인된 선화 또는 서버의 미리보기 요청으로 PLAN을 생성하며 작업을 자동 등록하지 않습니다.
사용자 그리기 클릭이 실행 승인입니다. 문구가 있으면 사진은 상단, 문구는 하단에 배치합니다.
`ART_JOB_PLAN_ROOT/<job_id>` 아래의 정해진 입력만 Action에서 읽습니다.
DrawingPlan v0.2를 원자적으로 공개하고 이미 공개된 계획을 덮어쓰지 않습니다.
DL은 선택적 별도 Python 환경이며 `requirements-dl.txt`와 `ART_DL_PYTHON`을 사용합니다.
시험은 저장소의 `tests/artwork_pipeline/`에 있습니다.

`standalone_drawer.py`는 제공된 `draw_image_standalone.py`를 실행하고 `live_control.py`를 통해 일시정지·홈·중단점 재개·정지와 외력 상태를 관측합니다. JobManager는 사용하지 않습니다. `recovery_store.py`는 정상 주행을 RAM에만 기록하고 예외 중단점만 SQLite에 보존합니다. `recovery_plan.py`는 재개 전 계획·보정·Tool/TCP를 대조합니다.

[현재 버튼 정책·외력 임시값·중단점 DB·팀 인계](../../../docs/CHECKPOINT_RECOVERY_KR.md)

[통합 UI·제어 설정·실행·시험 안내](../../../docs/UNIFIED_UI_CONTROL_KR.md)
