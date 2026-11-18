# 중단점 복구와 새 그림 시작 — 팀 인계

이번 변경은 로컬 A4에만 반영했습니다. JobManager는 추가하지 않았습니다. SQLite는 중단점 보존에만 사용하며 사진·선화·DrawingPlan 전체를 DB에 복사하지 않습니다. 기존 필압·기준면 측정·좌표 변환과 Tool/TCP 기본값은 유지했습니다.

## 버튼 정책

- **그리기**: 새 도안을 시작합니다. 이전 실행이 있으면 내부 `REPLACE` 명령으로 이동 정지, 필요한 펜 반납·홈 복귀, 실행 종료와 실제 정지를 확인한 뒤 새 작업을 등록합니다. 별도의 허용 체크박스는 없습니다. 확인에 실패하면 새 로봇 명령을 보내지 않습니다.
- **일시정지**: 현재 모션을 정지하고 중단점을 저장한 뒤 기존 상승·홈 경로로 이동합니다.
- **정지 · 이어그리기 보존**: 현재 모션을 정지하고 중단점을 보존합니다. 같은 계획을 처음부터 다시 그리지 않습니다. 기존 API의 `RESET`도 이 의미로 처리합니다.
- **재개**: 같은 그림의 중단점으로 복귀합니다. 이미 완료한 획은 다시 시작하지 않습니다. 일시정지 후에는 저장한 홈 왕복 관절 경로를 거칩니다. 외력 정지에서는 원인 제거와 정상 상태를 확인해야 재개합니다.

팀원이 정책을 바꿀 위치는 `workflow.py`의 `finish_previous_for_new_drawing()`와 `standalone_drawer.py`의 `_reconcile_session()`입니다. 두 곳에 `POLICY-01`과 `TODO(팀 인계)` 주석을 남겼습니다. 새 그리기는 이전 그림을 종료하지만 과거 계획·사진·중단점 이력은 삭제하지 않습니다. 새 그림을 시작한 뒤 종료한 옛 그림을 자동 재개하지 않습니다.

## 복귀점과 실제 좌표의 차이

현재 이동 중인 점을 이미 도달한 점으로 처리하면 그리지 않은 선을 건너뛸 수 있습니다. 따라서 복귀 목표는 현재 선분의 **시작점인 마지막 계획 웨이포인트**입니다. 해당 선분은 시작점부터 다시 그려 빈틈을 줄입니다. 부분적으로 겹쳐 그리는 구간은 생길 수 있으며 잉크 품질은 실물로 확인해야 합니다.

저장 데이터는 다음처럼 구분합니다.

- `stroke_id`, `point_index`: 진행 중인 선분의 다음 목표점 인덱스입니다. 복귀점은 같은 획의 `point_index - 1`입니다.
- `target_pose`: 계획에서 다시 계산·검증한 복귀점입니다.
- `inflight_target_pose`: 중단 당시 진행 중이던 다음 목표점입니다.
- `last_safe_actual_pose`: 외력 기준을 넘기기 전 정상 선분 안에서 관측한 실제 좌표입니다.
- `actual_pose_at_fault`: 사건 후 실제 위치입니다. 감사·진단용이며 그리기 재개 목표로 사용하지 않습니다.
- `plan_path`, `plan_sha256`: 원본 파일 위치와 SHA-256입니다. 재개 때 보정 파일 해시, Tool/TCP, 펜, 획·점 인덱스, 누적 길이도 대조합니다.

정상 주행 샘플은 `RecoveryJournal.samples`의 `deque(maxlen=100)`에만 기록합니다. 모션 루프의 대기 간격은 20ms이며 ROS 호출 시간이 더해지므로 엄밀한 50Hz 실시간 보장은 아닙니다. 정상 샘플마다 SQLite를 쓰지 않습니다.

정지·외력 사건마다 `recovery_checkpoints`에 한 행을 저장합니다. 같은 사건의 중복 저장을 막습니다. 홈 도달, 재개, 완료, 이전 그림 종료 같은 저빈도 상태 전이에서는 기존 기록을 갱신합니다. WAL과 `synchronous=FULL`을 사용합니다. 네트워크 공유 폴더 대신 로컬 디스크를 사용하세요.

## 저장 위치와 확인 방법

기본 DB는 `ART_JOB_PLAN_ROOT/.recovery/recovery.sqlite3`입니다. 작업 루트를 지정하지 않았다면 `~/A4/data/jobs/.recovery/recovery.sqlite3`입니다. 별도 경로는 모든 A4 프로세스에 같은 `ART_RECOVERY_DB`를 설정합니다. 첫 사건 이전에는 DB 파일이 없는 것이 정상입니다.

```bash
export ART_JOB_PLAN_ROOT="$HOME/A4/data/jobs"
# 필요한 경우에만 별도 DB 경로를 지정합니다.
# export ART_RECOVERY_DB="$HOME/A4/data/recovery.sqlite3"

sqlite3 -readonly "$ART_JOB_PLAN_ROOT/.recovery/recovery.sqlite3" \
  'SELECT job_id,cause,state,stroke_id,point_index,datetime(created_at,"unixepoch","localtime") FROM recovery_checkpoints ORDER BY created_at DESC;'
```

`pending`은 중단점 대기, `resuming`은 복구 중, `resolved`는 완료, `abandoned`는 새 그림 선택으로 종료, `superseded`는 더 최근 중단점으로 대체된 이력입니다. DB 행이나 실행 포인터 파일을 삭제해 실제 정지 확인을 우회하지 마세요.

## 재시작 후 재개

노드가 시작되면 미해결 중단점을 읽고 `RECOVERY_REQUIRED`(복구 준비 필요)를 표시합니다. 자동 이동하지 않습니다. 같은 종이·펜·보정·Tool/TCP를 유지하고 실제 로봇을 정상 상태로 준비한 뒤 **재개**를 누릅니다. 재시작 복구에서는 최초 펜 개폐·초기 홈 이동·접촉 재측정을 반복하지 않습니다.

복구는 현재 자세 확인 → 안전 상승 → 저장한 계획점 상부 → 계획점 하강 → 남은 경로 순서입니다. 홈으로 이동한 일시정지는 먼저 저장된 관절 왕복 경로를 사용합니다. 방향 차이, 복구 영역 이탈, 상승 높이 초과, 변경된 계획·보정, 서비스 오류는 복귀를 거절합니다. 보호 정지 해제나 서보 ON을 자동 수행하지 않습니다.

이미 저장한 예외 이후의 재시작은 복구 대상입니다. 반면 정상 주행 중 전원이 갑자기 끊겨 예외 저장 코드가 실행되지 않았다면 RAM의 최신 위치를 복원할 수 없습니다. 이 구조가 모든 전원 차단 시점의 정확한 위치를 보장하지는 않습니다. 준비·펜 교환 중처럼 유효한 드로잉 웨이포인트가 없는 사건은 이어 그리기를 거절합니다. 확인 가능한 파지 물체 기록이 있으면 새 그림 전 정리만 수행할 수 있습니다.

## 외력 값 수정 위치

현재 PC의 파일은 `~/.ros/a4_motion_control.json`입니다. `ART_MOTION_CONTROL_CONFIG`를 지정하면 그 파일을 사용합니다. 배포용 예시는 `ros2_ws/src/art_artwork_pipeline/config/motion_control.example.json`입니다. 예시는 `validated=false`이므로 그대로 실물 실행하지 않습니다.

```json
{
  "protection_mode": "software_force",
  "force_limits": [8.0, 8.0, 12.0, 1.0, 1.0, 1.0],
  "force_bias": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
  "force_limits_provisional": true,
  "recovery_lift_mm": 15.0,
  "recovery_orientation_tolerance_deg": 1.0
}
```

배열 순서는 Fx, Fy, Fz, Mx, My, Mz입니다. 앞 세 값은 N, 뒤 세 값은 Nm입니다. `abs(관측값 - force_bias) > force_limits`이면 정지합니다. 위 값은 요청에 따른 **미측정 임시값**이며 인체 접촉을 안전하게 검출한다는 의미가 아닙니다. 정상 접촉력·가감속만으로 정지할 수도 있습니다. 현재 힘의 정상 편차를 측정하고 장비 담당자가 조정해야 합니다. 설정 변경 후 관련 A4 노드를 재시작하세요.

`get_tool_force`의 TCP 힘 추정과 제어기 알람을 감시하는 기능이며 로봇 몸체 모든 부위 접촉을 보장하는 안전 센서는 아닙니다. 티치펜던트 충돌 감지·보호 정지·물리 비상정지를 유지합니다. 기존 필압·접촉 측정 알고리즘은 수정하지 않았습니다.

- [두산 get_tool_force 공식 설명](https://manual.doosanrobotics.com/en/programming-manual/3.4.0/publish/get_tool_force-ref)
- [SQLite WAL 공식 설명](https://www.sqlite.org/wal.html)

## 담당 파일

- `recovery_store.py`: RAM 샘플, 사건 저장, 중단점 이력과 상태 전이입니다.
- `recovery_plan.py`: 불변 계획·보정·Tool/TCP·인덱스 재검증입니다.
- `live_control.py`: 실제 정지 관측, 중단점 저장, 재개 준비와 복귀 모션입니다.
- `draw_image_standalone.py`: 기존 장비 모션에 중단점 이후의 경로만 연결하고 파지 물체를 복원합니다.
- `standalone_drawer.py`: 프로세스 재시작 복구, 이전 실행 정리와 ROS 서비스를 담당합니다.
- `workflow.py`, `app.js`, `index.html`: 별도 허용 버튼 없는 새 그림 시작과 중단점 재개 UI입니다.

실물 M0609·RG2 이동, 정지 거리, 충돌 검출, 잉크 연속성은 이번 자체 시험에서 검증하지 않았습니다. 자동 시험 결과는 모의 장비에 대한 결과입니다.
