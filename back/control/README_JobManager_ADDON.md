# A4 JobManager 신규 패키지 추가 ZIP (기존 파일 덮어쓰기 없음)

이 ZIP은 앞서 동작 확인한 `~/A4`에 **새 파일만 추가**하기 위한 패키지입니다.
기존 `ros2_ws/src/art_kiosk_bridge`, `ros2_ws/src/art_interfaces`, `tests/integration`은 포함하거나 수정하지 않습니다.

## 폴더 트리

```text
A4/
├── ros2_ws/src/art_job_manager/       # 신규 JobManagerNode + SQLite
│   ├── README.md                      # 이 패키지 설명
│   ├── package.xml, setup.py, setup.cfg
│   ├── resource/art_job_manager
│   └── art_job_manager/
│       ├── job_manager_node.py
│       ├── job_engine.py
│       ├── job_repository.py
│       ├── plan.py
│       └── __init__.py
├── tests/job_manager/                 # 신규 unit + ROS 통합시험
│   ├── conftest.py
│   ├── test_job_engine.py
│   └── test_job_manager_ros.py
├── examples/job_manager/              # 신규 검증용 DrawingPlan
│   ├── create_demo_plan.py
│   └── JOB_SIM_001/drawing_plan.json
└── docs/job_manager_integration.md    # 신규 팀 연계 계약
```

## 설치

```bash
# 다운로드한 ZIP이 ~/Downloads/A4_JobManager_addon.zip 에 있다고 가정
unzip -n ~/Downloads/A4_JobManager_addon.zip -d ~/A4

cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-up-to art_job_manager
source install/setup.bash
ros2 pkg executables art_job_manager
```

## 실행

**이전에 켠 Mock JobManager를 먼저 Ctrl+C로 종료해야 합니다.**
정확한 터미널별 명령은 `ros2_ws/src/art_job_manager/README.md`에 있습니다.

## 테스트 현황

- 개발 컨테이너 Python 단위시험: **12 passed**.
- ROS 2 실제 통신시험: 이 컨테이너에는 `rclpy`가 없어서 **1 skipped**.
- 사용자의 실제 Ubuntu+Jazzy PC에서 `ros2 run` 및 `pytest` 재검증 필요.
