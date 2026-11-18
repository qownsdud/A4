# art_state_store

기존 `ros2_ws` 파이썬 코드를 수정하지 않고 독립적으로 추가된 **SQLite 영속 상태 저장소 + 코드(RAM) 실시간 웨이포인트 링 버퍼** 모듈입니다.

`COLCON_IGNORE`가 포함되어 있어 기존 `colcon build`에 영향을 주지 않습니다.

## 파일 구성

### `schema.sql`
- SQLite 테이블 6종(`jobs`, `artwork_preparations`, `calibration_runs`, `command_receipts`, `recovery_checkpoints`, `job_events`)과 인덱스 정의 파일입니다.

### `sqlite_store.py` (`RobotStateStore`)
- SQLite DB를 WAL 모드로 열고 트랜잭션 기반으로 작업 상태, 명령 중복 방지, 캘리브레이션 결과, 외력 복구 체크포인트, 이벤트 로그를 저장·조회합니다.

### `motion_buffer.py` (`MotionRingBuffer`, `ExternalForceGuard`)
- DB에 저장하지 않고 **로봇 제어 코드의 메모리(RAM) 상에서만** 고빈도 실시간 좌표·외력(`MotionSample`)을 `collections.deque` 링 버퍼로 유지합니다.
- 외력이 임계값을 초과해 정지해야 할 때만 버퍼에서 직전 정상 웨이포인트를 추출해 `RecoveryWaypoint`를 생성하며, 이를 `RobotStateStore.save_recovery_checkpoint(...)`로 전달해 SQLite에 1건 저장합니다.

### `COLCON_IGNORE` / `__init__.py`
- `COLCON_IGNORE`: ROS2 `colcon build` 시 기존 패키지 빌드를 방해하지 않기 위한 마커 파일입니다.
- `__init__.py`: 외부에서 `art_state_store` 모듈을 바로 import 할 수 있도록 주요 클래스를 노출합니다.

## 기본 사용 흐름 예시

```python
from art_state_store import ExternalForceGuard, RobotStateStore

store = RobotStateStore("~/A4/data/art_state.db")
guard = ExternalForceGuard(force_limit_n=15.0, buffer_maxlen=100)

# 1) 주행 중 매 틱마다 코드 메모리(링 버퍼)에만 기록
exceeded = guard.record_tick(
    pen_idx=0,
    stroke_idx=12,
    point_idx=4,
    held_item_name="펜 1",
    target_pose=[400.0, 100.0, 50.0, 0.0, 180.0, 0.0],
    actual_pose=[400.1, 100.0, 50.0, 0.0, 180.0, 0.0],
    tool_force=[0.2, 0.1, -2.5, 0.0, 0.0, 0.0],
)

# 2) 외력 초과 감지 시에만 직전 정상 웨이포인트를 SQLite에 1건 저장
if exceeded:
    wp = guard.buffer.build_recovery_waypoint(
        fault_actual_pose=[403.5, 101.2, 50.0, 0.0, 180.0, 0.0],
        fault_tool_force=[18.0, 4.0, -5.0, 0.0, 0.0, 0.0],
        force_limit_n=15.0,
    )
    if wp is not None:
        store.save_recovery_checkpoint(**wp.to_db_kwargs(job_id="JOB_001"))
```
