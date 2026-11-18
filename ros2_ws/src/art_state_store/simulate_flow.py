"""art_state_store 전체 흐름(아트워크 -> 캘리브레이션 -> 주행 -> 외력정지 -> 재시작복구 -> 완료) 시뮬레이션."""

from __future__ import annotations

import argparse
from pathlib import Path
import tempfile

from art_state_store import ExternalForceGuard, RobotStateStore


def run_simulation(db_path: Path) -> None:
    store = RobotStateStore(db_path)
    guard = ExternalForceGuard(force_limit_n=15.0, buffer_maxlen=50)
    job_id = "JOB_SIM_001"

    print(f"[1] SQLite DB 생성: {db_path}")

    # 1. 아트워크 준비 메타데이터 저장
    store.upsert_artwork_preparation(
        job_id=job_id,
        stage="PREPARED",
        method="cv",
        paper="a4",
        detail="medium",
        seed=42,
        calligraphy_text="HELLO",
        input_path="/tmp/sim/photo.png",
        lineart_path="/tmp/sim/lineart.png",
        preview_path="/tmp/sim/preview.svg",
        plan_path="/tmp/sim/drawing_plan.json",
        approved=True,
        confirmed=True,
    )

    # 2. 작업 등록
    store.create_job(
        job_id=job_id,
        plan_path="/tmp/sim/drawing_plan.json",
        strokes_path="/tmp/sim/standalone_strokes.json",
        plan_sha256="sim_sha256_deadbeef",
        total_strokes=10,
        state="CALIBRATING",
        current_pen="PEN_1",
        message="캘리브레이션을 시작합니다.",
    )
    store.append_event(job_id=job_id, event_type="STATE_CHANGED", state="CALIBRATING", detail="작업 시작")

    # 3. 캘리브레이션 결과 저장
    contact_pose = [400.0, 100.0, 48.5, 0.0, 180.0, 0.0]
    store.save_calibration_run(
        job_id=job_id,
        auto_calibrate=True,
        virtual=True,
        slope_a=0.0012,
        slope_b=-0.0008,
        contact_pose=contact_pose,
        safe_rect=[350.0, 550.0, 50.0, 200.0],
    )
    store.update_job(job_id, state="DRAWING", message="로봇이 그리기를 진행 중입니다.")
    print("[2] 작업 등록 및 캘리브레이션 저장 완료")

    # 4. 정상 주행 시뮬레이션 (코드 RAM 링 버퍼에만 기록, SQLite 쓰기 없음)
    waypoints = [
        (0, 1, 0, [400.0, 100.0, 48.5, 0.0, 180.0, 0.0]),
        (0, 1, 1, [405.0, 100.0, 48.5, 0.0, 180.0, 0.0]),
        (0, 1, 2, [410.0, 100.0, 48.5, 0.0, 180.0, 0.0]),
        (0, 2, 0, [410.0, 110.0, 48.5, 0.0, 180.0, 0.0]),
        (0, 2, 1, [415.0, 110.0, 48.5, 0.0, 180.0, 0.0]),
    ]
    for pen_idx, stroke_idx, point_idx, target in waypoints:
        actual = [target[0] + 0.05, target[1] - 0.03, target[2], 0.0, 180.0, 0.0]
        exceeded = guard.record_tick(
            pen_idx=pen_idx,
            stroke_idx=stroke_idx,
            point_idx=point_idx,
            held_item_name="펜 1",
            target_pose=target,
            actual_pose=actual,
            tool_force=[0.4, -0.2, -2.1, 0.0, 0.0, 0.0],
        )
        assert not exceeded
        store.update_job(job_id, completed_strokes=stroke_idx)
    print(f"[3] 정상 주행 {len(waypoints)}틱 완료 (메모리 링 버퍼 유지)")

    # 5. 외력 감지 이벤트 발생 (로봇이 밀림)
    fault_target = [420.0, 110.0, 48.5, 0.0, 180.0, 0.0]
    fault_actual = [424.8, 113.2, 49.0, 0.0, 180.0, 0.0]
    fault_force = [19.5, 8.2, -4.0, 0.0, 0.0, 0.0]
    exceeded = guard.record_tick(
        pen_idx=0,
        stroke_idx=2,
        point_idx=2,
        held_item_name="펜 1",
        target_pose=fault_target,
        actual_pose=fault_actual,
        tool_force=fault_force,
    )
    assert exceeded, "외력 임계값 초과가 감지되어야 합니다."

    wp = guard.buffer.build_recovery_waypoint(
        fault_actual_pose=fault_actual,
        fault_tool_force=fault_force,
        force_limit_n=15.0,
        trigger_reason="EXTERNAL_FORCE",
    )
    assert wp is not None
    cp_id = store.save_recovery_checkpoint(**wp.to_db_kwargs(job_id=job_id, contact_pose=contact_pose))
    store.update_job(job_id, state="RECOVERY_REQUIRED", error_code="EXTERNAL_FORCE", message="외력 감지로 정지했습니다.")
    store.append_event(
        job_id=job_id,
        event_type="ERROR",
        state="RECOVERY_REQUIRED",
        current_pen="PEN_1",
        completed_strokes=2,
        detail=f"외력 감지 (checkpoint_id={cp_id}, stroke={wp.stroke_idx}, point={wp.point_idx})",
    )
    print(f"[4] 외력 감지 -> SQLite 복구 웨이포인트 저장 완료 (stroke={wp.stroke_idx}, point={wp.point_idx}, target={wp.target_pose[:3]})")

    # 6. 제어 명령 중복 방지(idempotency) 테스트
    req_id = "req-cancel-001"
    store.save_command_receipt(
        job_id=job_id,
        request_id=req_id,
        command="CANCEL",
        accepted=True,
        state="STOPPING",
        message="중단 요청 수락",
    )
    receipt = store.get_command_receipt(job_id, req_id)
    assert receipt is not None and receipt["command"] == "CANCEL"
    print("[5] 명령 중복 방지 영수증(command_receipts) 확인 완료")

    # 7. 노드 재시작 후 DB에서 복귀 웨이포인트 조회 및 이어 그리기 완료 시뮬레이션
    store.close()
    restarted_store = RobotStateStore(db_path)
    pending = restarted_store.get_pending_checkpoint(job_id)
    assert pending is not None
    assert pending["stroke_idx"] == 2 and pending["point_idx"] == 1
    assert pending["target_pose"][:3] == [415.0, 110.0, 48.5]
    assert pending["actual_pose"][:3] == [424.8, 113.2, 49.0]
    print(f"[6] 재시작 후 DB에서 복귀 좌표 로드 성공: target={pending['target_pose'][:3]}, fault={pending['actual_pose'][:3]}")

    restarted_store.mark_checkpoint_status(pending["id"], "RECOVERED")
    restarted_store.update_job(
        job_id,
        state="COMPLETED",
        completed_strokes=10,
        error_code="",
        message="복구 후 드로잉 완료",
    )
    restarted_store.append_event(
        job_id=job_id,
        event_type="RECOVERY",
        state="COMPLETED",
        current_pen="PEN_3",
        completed_strokes=10,
        detail="복귀 완료 후 전체 획 종료",
    )
    assert restarted_store.get_pending_checkpoint(job_id) is None
    final_job = restarted_store.get_job(job_id)
    assert final_job is not None and final_job["state"] == "COMPLETED"
    print(f"[7] 최종 상태 확인: state={final_job['state']}, completed_strokes={final_job['completed_strokes']}/{final_job['total_strokes']}")
    restarted_store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="art_state_store 전체 흐름 시뮬레이션")
    parser.add_argument("--db", default="", help="유지할 SQLite DB 경로 (비우면 임시 폴더에서 실행 후 정리)")
    args = parser.parse_args()

    if args.db:
        run_simulation(Path(args.db))
        print(f"시뮬레이션 성공! DB 파일 확인: {args.db}")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            run_simulation(Path(tmp) / "sim_art_state.db")
        print("시뮬레이션 성공! (오류 없음)")


if __name__ == "__main__":
    main()
