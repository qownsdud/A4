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
DL은 선택적 별도 Python 환경이며 `requirements-dl.txt`와 `ART_DL_PYTHON`을 사용합니다. 제공된 인물 사진으로 실제 혼합 모델 추론을 확인했습니다. 가상환경과 얼굴 모델 설치는 아래 통합 안내를 따릅니다.
시험은 저장소의 `tests/artwork_pipeline/`에 있습니다.

[의존성·DL 분리·실행·검증 안내](../../../docs/ROS2_PACKAGE_REFACTOR_KR.md)

[가로 A4·혼합 선화 통합과 실물 연결 조건](../../../docs/REFERENCE_INTEGRATION_KR.md)
