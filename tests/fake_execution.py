"""HTTP 계약 시험 전용 관측 상태. JobManager·SQLite 구현이 아닙니다."""

from pathlib import Path
from types import SimpleNamespace as Reply
import json
from art_artwork_pipeline.plan import load_plan, PlanError
from art_artwork_pipeline.live_control import length


class FakeExecutionBackend:
    def __init__(self, *, plan_root):
        self.root = Path(plan_root)
        self.rows = {}
        self.receipts = {}

    def create_job(self, job_id, plan_path):
        try:
            summary = load_plan(job_id, plan_path, plan_root=self.root)
        except PlanError as exc:
            return Reply(
                accepted=False,
                job_id=job_id,
                state="STOPPED",
                error_code=str(exc),
                message=str(exc),
            )
        if job_id in self.rows:
            return Reply(
                accepted=True,
                job_id=job_id,
                state=self.rows[job_id]["state"],
                error_code="",
                message="동일 등록",
            )
        if any(r["state"] not in ("STOPPED", "COMPLETED") for r in self.rows.values()):
            return Reply(
                accepted=False,
                job_id=job_id,
                state="DRAWING",
                error_code="JOB_ALREADY_ACTIVE",
                message="작업 중",
            )
        plan = json.loads(Path(summary.path).read_text())
        self.rows[job_id] = dict(
            job_id=job_id,
            state="DISPATCHING",
            completed_strokes=0,
            total_strokes=summary.stroke_count,
            current_pen="",
            error_code="",
            message="",
            total_length_mm=sum(length(s["points_mm"]) for s in plan["strokes"]),
            completed_length_mm=0.0,
            external_force=False,
            run_id=1,
        )
        return Reply(
            accepted=True,
            job_id=job_id,
            state="DISPATCHING",
            error_code="",
            message="등록",
        )

    def status(self, job_id):
        return dict(self.rows[job_id]) if job_id in self.rows else None

    def statuses(self):
        return list(self.rows.values())

    def confirm_state(self, job_id, state):
        self.rows[job_id]["state"] = state
        return True

    def control_job(self, job_id, command, request_id):
        key = (job_id, request_id)
        if key in self.receipts:
            previous, result = self.receipts[key]
            if previous == command:
                return result
            return Reply(
                accepted=False,
                job_id=job_id,
                state=self.rows[job_id]["state"],
                error_code="REQUEST_ID_CONFLICT",
                message="중복 충돌",
            )
        allowed = {
            "PAUSE": ("DRAWING",),
            "RESUME": ("PAUSED",),
            "RESET": ("DRAWING", "PAUSED", "FORCE_STOPPED", "COMPLETED"),
            "CANCEL": ("DISPATCHING", "DRAWING", "PAUSED", "RESUMING"),
        }
        state = self.rows[job_id]["state"]
        if state not in allowed.get(command, ()):
            return Reply(
                accepted=False,
                job_id=job_id,
                state=state,
                error_code="INVALID_TRANSITION",
                message="상태 오류",
            )
        target = {
            "PAUSE": "PAUSING",
            "RESUME": "RESUMING",
            "RESET": "RESETTING",
            "CANCEL": "STOPPED",
        }[command]
        self.confirm_state(job_id, target)
        reply = Reply(
            accepted=True,
            job_id=job_id,
            state=target,
            error_code="",
            message="요청 수락",
        )
        self.receipts[key] = (command, reply)
        return reply

    def close(self):
        self.rows.clear()
