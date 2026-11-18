# [파일 역할] KioskBridge 초기 통신용 Mock JobManager
# [동작] JobManager가 없을 때 CreateJob/ControlJob 서비스를 가짜로 제공하는 테스트 노드입니다.
# [주의] 운영용 JobManager 및 시험용 JobManager와 동시에 실행하지 마세요.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""ROS 2 Mock JobManager: tests HTTP↔ROS without any Doosan driver.

TEAM_SYNC(JobManager/Robot): This is not the real JobManager. It simulates
states and does not prove that a real robot stopped, lifted its pen, or resumed.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

import rclpy
from rclpy.node import Node
from art_interfaces.msg import JobStatus
from art_interfaces.srv import ControlJob, CreateJob


@dataclass
class FakeJob:
    job_id: str
    state: str = "DRAWING"
    completed: int = 0
    total: int = 20
    pending_state: str | None = None
    transition_after: float = 0.0


class MockJobManager(Node):
    def __init__(
        self,
        *,
        create_service: str = "/art/create_job",
        control_service: str = "/art/control_job",
        status_topic: str = "/art/job_status",
        progress_period_sec: float = 0.25,
        total_strokes: int = 20,
    ) -> None:
        super().__init__("mock_job_manager")
        self.jobs: dict[str, FakeJob] = {}
        self.requests_seen: dict[tuple[str, str], tuple[bool, str, str, str]] = {}
        self.total_strokes = total_strokes
        self.publisher = self.create_publisher(JobStatus, status_topic, 10)
        self.create_srv = self.create_service(CreateJob, create_service, self.on_create)
        self.control_srv = self.create_service(ControlJob, control_service, self.on_control)
        self.timer = self.create_timer(progress_period_sec, self.tick)

    def publish(self, job: FakeJob, message: str = "Mock status only") -> None:
        msg = JobStatus()
        msg.job_id = job.job_id
        msg.state = job.state
        msg.completed_strokes = job.completed
        msg.total_strokes = job.total
        msg.current_pen = "PEN_1"
        msg.error_code = ""
        msg.message = message
        self.publisher.publish(msg)

    @staticmethod
    def respond(response, *, accepted: bool, job_id: str, state: str,
                error_code: str = "", message: str = ""):
        response.accepted = accepted
        response.job_id = job_id
        response.state = state
        response.error_code = error_code
        response.message = message
        return response

    def on_create(self, request, response):
        # TEAM_SYNC(Backend): plan_path must be verified/owned by the real Manager.
        if request.job_id in self.jobs:
            j = self.jobs[request.job_id]
            return self.respond(response, accepted=False, job_id=j.job_id,
                                state=j.state, error_code="DUPLICATE_JOB")
        if not request.plan_path:
            return self.respond(response, accepted=False, job_id=request.job_id,
                                state="REJECTED", error_code="MISSING_PLAN")
        job = FakeJob(job_id=request.job_id, total=self.total_strokes)
        self.jobs[job.job_id] = job
        self.publish(job)
        return self.respond(response, accepted=True, job_id=job.job_id,
                            state=job.state, message="MOCK ONLY: job accepted")

    def on_control(self, request, response):
        key = (request.job_id, request.request_id)
        # TEAM_SYNC(JobManager): implement deduplication and persistent request IDs in real code.
        if key in self.requests_seen:
            accepted, state, error, message = self.requests_seen[key]
            return self.respond(response, accepted=accepted, job_id=request.job_id,
                                state=state, error_code=error, message=message)
        j = self.jobs.get(request.job_id)
        if j is None:
            return self.respond(response, accepted=False, job_id=request.job_id,
                                state="UNKNOWN", error_code="JOB_NOT_FOUND")
        if request.command == "PAUSE" and j.state == "DRAWING":
            j.state = "PAUSING"
            j.pending_state = "PAUSED"
        elif request.command == "RESUME" and j.state == "PAUSED":
            j.state = "DRAWING"
        elif request.command == "CANCEL" and j.state in {"DRAWING", "PAUSING", "PAUSED"}:
            j.state = "STOPPING"
            j.pending_state = "STOPPED"
        else:
            result = (False, j.state, "INVALID_TRANSITION", "Command rejected")
            self.requests_seen[key] = result
            return self.respond(response, accepted=result[0], job_id=j.job_id,
                                state=result[1], error_code=result[2], message=result[3])
        if j.pending_state:
            j.transition_after = time.monotonic() + 0.25
        result = (True, j.state, "", "MOCK ONLY: request accepted")
        self.requests_seen[key] = result
        self.publish(j)
        return self.respond(response, accepted=result[0], job_id=j.job_id,
                            state=result[1], error_code=result[2], message=result[3])

    def tick(self) -> None:
        now = time.monotonic()
        for j in self.jobs.values():
            if j.pending_state and now >= j.transition_after:
                j.state = j.pending_state
                j.pending_state = None
                self.publish(j)
            elif j.state == "DRAWING":
                j.completed = min(j.completed + 1, j.total)
                if j.completed >= j.total:
                    j.state = "COMPLETED"
                self.publish(j)


# [핵심 기능] 실행 진입점: 환경 변수, ROS 초기화, spin 및 종료 처리
def main() -> None:
    parser = argparse.ArgumentParser(description="Mock JobManager; NO real robot commands")
    parser.add_argument("--strokes", type=int, default=20)
    parser.add_argument("--period", type=float, default=0.25)
    args = parser.parse_args()
    if args.strokes < 1 or args.period <= 0:
        parser.error("--strokes and --period must be positive")
    rclpy.init()
    node = MockJobManager(total_strokes=args.strokes, progress_period_sec=args.period)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
