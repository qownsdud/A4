"""JobStateMachine 및 DecisionSink 단방향 전달 단위 테스트."""

import json
from pathlib import Path

from art_job_manager.decision_port import MemoryDecisionSink
from art_job_manager.state_machine import JobStateMachine


def _create_plan_file(root: Path, job_id: str) -> str:
    job_dir = root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "drawing_plan.json"
    payload = {
        "schema_version": "0.2",
        "job_id": job_id,
        "unit": "mm",
        "coordinate_frame": "paper_top_left_x_right_y_down",
        "paper_mm": {"width": 297, "height": 210},
        "strokes": [
            {"stroke_id": 1, "execution_order": 0, "pen_id": "PEN_1", "points_mm": [[10, 10], [20, 20]]},
            {"stroke_id": 2, "execution_order": 1, "pen_id": "PEN_2", "points_mm": [[30, 30], [40, 40]]},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_full_lifecycle_and_decisions(tmp_path: Path):
    sink = MemoryDecisionSink()
    machine = JobStateMachine(plan_root=tmp_path, decision_sink=sink)
    p1 = _create_plan_file(tmp_path, "J1")
    p2 = _create_plan_file(tmp_path, "J2")

    r1 = machine.create_job("J1", p1)
    assert r1.accepted and r1.state == "QUEUED"

    # 단일 활성 작업 제한 확인
    r_busy = machine.create_job("J2", p2)
    assert not r_busy.accepted and r_busy.error_code == "SYSTEM_BUSY"

    dispatch = machine.prepare_dispatch("J1")
    assert dispatch is not None and dispatch.start_stroke_id == 1
    assert machine.status("J1").state == "DISPATCHING"

    assert machine.on_feedback("J1", event="STARTED_LIVE")
    assert machine.status("J1").state == "DRAWING"

    # 펜 이격 미확인 획 완료는 무시
    assert not machine.on_feedback("J1", event="STROKE_COMPLETED", stroke_id=1, pen_id="PEN_1", pen_up_confirmed=False)
    assert machine.status("J1").completed_strokes == 0

    # 펜 이격 확인 시 획 완료 반영
    assert machine.on_feedback("J1", event="STROKE_COMPLETED", stroke_id=1, pen_id="PEN_1", pen_up_confirmed=True)
    assert machine.status("J1").completed_strokes == 1
    assert machine.status("J1").current_pen == "PEN_2"

    # PAUSE -> PAUSED -> RESUME -> DRAWING
    c_pause = machine.control_job("J1", "PAUSE", "REQ_1")
    assert c_pause.accepted and c_pause.state == "PAUSING"
    # 동일 request_id 재요청 시 멱등성 확인
    assert machine.control_job("J1", "PAUSE", "REQ_1") == c_pause
    # 동일 request_id 다른 명령 충돌 확인
    assert machine.control_job("J1", "RESUME", "REQ_1").error_code == "REQUEST_ID_CONFLICT"

    machine.on_control_reply("J1", "PAUSE", True)
    assert machine.status("J1").state == "PAUSED"

    assert machine.control_job("J1", "RESUME", "REQ_2").state == "RESUMING"
    machine.on_control_reply("J1", "RESUME", True)
    assert machine.status("J1").state == "DRAWING"

    assert machine.on_feedback("J1", event="STROKE_COMPLETED", stroke_id=2, pen_id="PEN_2", pen_up_confirmed=True)
    ok = machine.on_action_result(
        "J1", ros_status=4, success=True, final_state="COMPLETED", completed_strokes=2, pen_up_confirmed=True
    )
    assert ok and machine.status("J1").state == "COMPLETED"
    assert machine.active_job() is None

    # 완료 후 새 작업 수락 확인
    assert machine.create_job("J2", p2).accepted
    assert [e.event_type for e in sink.events[:4]] == [
        "JOB_CREATED",
        "JOB_REJECTED",
        "JOB_DISPATCHED",
        "STATE_CHANGED",
    ]
    assert any(e.event_type == "JOB_FINISHED" and e.state == "COMPLETED" for e in sink.events)


def test_failure_ends_stopped_without_locking_next_job(tmp_path: Path):
    sink = MemoryDecisionSink()
    machine = JobStateMachine(plan_root=tmp_path, decision_sink=sink)
    p1 = _create_plan_file(tmp_path, "J_FAIL")
    p2 = _create_plan_file(tmp_path, "J_NEXT")

    assert machine.create_job("J_FAIL", p1).accepted
    assert machine.prepare_dispatch("J_FAIL") is not None
    assert machine.mark_failed("J_FAIL", "DRIVER_ERROR", "통신 실패")
    assert machine.status("J_FAIL").state == "STOPPED"
    assert machine.create_job("J_NEXT", p2).accepted
