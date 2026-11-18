# A4 실제 JobManager ↔ DrawingController Action 연동 v1

> 기존 `job_manager`(내장 시뮬레이션)와 별도 실행 명령 `job_manager_real`을 추가한다. **서버가 없을 때는 QUEUED 대기만 하고 가짜 획을 실행하지 않는다.** 실제 Doosan 모션은 팀원 DrawingController Action Server가 구현해야 한다.

## 0. 포함 파일

```text
ros2_ws/src/art_interfaces/action/ExecuteDrawing.action   # 신규 Controller Action 계약
ros2_ws/src/art_interfaces/CMakeLists.txt                 # Action 인터페이스 빌드 추가
ros2_ws/src/art_job_manager/art_job_manager/
    production_engine.py                                 # 신규 SQLite 상태/중복·복구 상태 머신
    real_job_manager_node.py                             # 신규 Action Client + 기존 Bridge Service/Topic
    job_repository.py,plan.py,job_engine.py,job_manager_node.py  # 이전 JobManager 소스 보존
ros2_ws/src/art_job_manager/{setup.py,package.xml}        # job_manager_real 진입점 추가
pytest tests/job_manager_v1/                              # 신규 오프라인 테스트, 가짜 Controller Action Server
README_REAL_JobManager.md, docs/TEAM_CONTRACT_V1.md       # 설치/팀 인계 규약
```

기존 `art_kiosk_bridge`와 기존 `CreateJob.srv`·`ControlJob.srv`·`JobStatus.msg`는 수정하지 않음. ZIP을 기존 A4에 덮어쓰기 전에 이전 `art_job_manager`와 `art_interfaces/CMakeLists.txt`를 백업할 것. Python의 테스트 환경에서 안전 로직 테스트를 수행했지만 **ROS 2 Jazzy 연동 빌드·실제 Controller 시험은 사용자 PC에서 확인할 것**.

## 1. 안전한 ZIP 적용 (기존 ROS 프로세스 먼저 모두 Ctrl+C)

```bash
cd ~/A4
mkdir -p ~/A4_BACKUP
cp -a ros2_ws/src/art_job_manager ~/A4_BACKUP/art_job_manager_before_v1
cp ros2_ws/src/art_interfaces/CMakeLists.txt ~/A4_BACKUP/art_interfaces_CMakeLists_before_v1.txt
# ZIP은 ~/Downloads/A4_JobManager_REAL_v1.zip에 다운로드한 상태라 가정
unzip -o ~/Downloads/A4_JobManager_REAL_v1.zip -d ~/A4
```

`unzip -o`는 ZIP에 포함된 같은 경로 파일을 덮어쓰므로 **사용자 작성분이 있다면 먼저 diff/백업**해야 한다. 변경 범위는 `art_job_manager`, `art_interfaces/CMakeLists.txt`, 신규 action/tests/docs/README. 다른 팀원 코드에는 적용하지 않는다.

## 2. 빌드 (Ubuntu 24.04 / ROS 2 Jazzy)

```bash
cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-up-to art_job_manager art_kiosk_bridge
source install/setup.bash
ros2 interface show art_interfaces/action/ExecuteDrawing
ros2 pkg executables art_job_manager
```

예상: `job_manager`(기존 모의용)와 `job_manager_real`(실제 Action Client) 두 실행 파일. 로봇 Action 서버는 아직 없으므로 **실제 Goal dispatch 테스트는 불가**하지만, Manager는 QUEUED 대기해야 정상.

## 3. 터미널별 실행 (실제 로봇 없이 v1 통신 시험)

가짜 Controller는 오직 계약 시험용이다. **실물 Doosan/ROS Driver를 연결한 환경에서는 실행하지 말 것.** 전용 `ROS_DOMAIN_ID=41`로 모든 테스트 터미널에서 분리한다.

**T1 — 가짜 Controller 테스트용 Action Server**

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=41
export A4_ENABLE_FAKE_CONTROLLER=YES
export A4_FAKE_STROKE_SECONDS=0.25
python3 tests/job_manager_v1/fake_drawing_controller.py
```

**T2 — 실제 JobManager 노드 (SIMULATE 아님)**

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=41
export ART_JOB_DB="$HOME/A4/data/jobs_real_v1_test.db"
export ART_JOB_PLAN_ROOT="$HOME/A4/examples/job_manager"
ros2 run art_job_manager job_manager_real
```

**T3 — 기존 Bridge**

```bash
cd ~/A4/ros2_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=41
ros2 run art_kiosk_bridge bridge
```

**T4 — 작업 생성 및 상태 조회**

```bash
cd ~/A4
python3 examples/job_manager/create_demo_plan.py JOB_V1_001 --strokes 60
curl http://127.0.0.1:8001/health
curl -X POST http://127.0.0.1:8001/bridge/jobs \
  -H 'Content-Type: application/json' \
  -d "{\"job_id\":\"JOB_V1_001\",\"plan_path\":\"$HOME/A4/examples/job_manager/JOB_V1_001/drawing_plan.json\"}"
curl http://127.0.0.1:8001/bridge/jobs/JOB_V1_001
# PAUSE: 작업이 완료되기 전에 실행 (60획 × 0.25s ≈ 15초 모의 진행)
curl -X POST http://127.0.0.1:8001/bridge/jobs/JOB_V1_001/control \
  -H 'Content-Type: application/json' \
  -d '{"command":"PAUSE","request_id":"v1_pause_001"}'
sleep 1
curl http://127.0.0.1:8001/bridge/jobs/JOB_V1_001
```

`PAUSED` 상태가 확인되고 `error_code`가 없다면 재개 테스트:

```bash
curl -X POST http://127.0.0.1:8001/bridge/jobs/JOB_V1_001/control \
  -H 'Content-Type: application/json' \
  -d '{"command":"RESUME","request_id":"v1_resume_001"}'
```

동일 `job_id`는 SQLite에서 영속적으로 중복 처리되므로 재시험 때 새 ID를 사용한다. 환경을 끄기 전에는 실제 액션 서버를 실행하지 말 것.

## 4. Python 테스트

```bash
cd ~/A4
python3 -m pytest tests/job_manager_v1 tests/job_manager tests/integration -q -rs
```

- CI/도구 환경에선 `rclpy`가 없어서 Python 단위·문법 검사만 검증 가능.
- ROS2 Jazzy가 설치된 사용자 PC에서는 별도로 `ros2 action list -t`에서 `/art/execute_drawing` 확인하고 v1 Action 흐름 검증.

## 5. 운영 모드 (컨트롤러 구현 후)

가짜 Controller 없이, 실제 `art_drawing_controller`가 v1 Action Server를 제공하도록 실행한다. Manager는 같은 `ROS_DOMAIN_ID`를 사용한다. Controller가 Goal을 거절하거나 안전한 Result를 못 보내면 JobManager는 `RECOVERY_REQUIRED`로 잠기고 자동 재개하지 않는다. `ART_JOB_DB` 실제 운영용 DB는 테스트용 DB와 분리한다. 통합 전에 `docs/TEAM_CONTRACT_V1.md`를 팀원과 검토·수락하고 실물 안전 절차·캘리브레이션·복구 승인 체계를 별도로 확정한다.
