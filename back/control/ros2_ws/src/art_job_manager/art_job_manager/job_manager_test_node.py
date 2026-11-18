# [파일 역할] 과거 JobManager 시뮬레이션 노드 (테스트 전용)
# [동작] 실제 Controller 없이 JobEngine의 가상 진행 및 상태 변화를 확인합니다.
# [주의] 실제 로봇 제어 검증에 사용하지 마세요. 실 Manager와 동시 실행 금지.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""TEST-ONLY ROS 2 JobManager adapter using exactly the Bridge contract.

Exposes /art/create_job, /art/control_job, /art/job_status.
The *only* autonomous progress option is an explicit simulation mode.
TEAM_SYNC(Controller): no actual hardware dispatch or Action binding yet.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

import rclpy
from rclpy.node import Node
from art_interfaces.msg import JobStatus
from art_interfaces.srv import ControlJob, CreateJob

from .job_engine import JobEngine


def env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser().resolve()


# [핵심 기능] 시뮬레이션/테스트 전용 JobManager의 ROS 인터페이스
class JobManagerNode(Node):
    def __init__(self, *, db_path: Path, plan_root: Path, simulation: bool,
                 create_service='/art/create_job', control_service='/art/control_job',
                 status_topic='/art/job_status', sim_period=0.25):
        super().__init__('job_manager_test_node')
        self.engine = JobEngine(db_path, plan_root=plan_root, simulation=simulation)
        self.simulation = simulation
        self.publisher = self.create_publisher(JobStatus, status_topic, 10)
        self.create_srv = self.create_service(CreateJob, create_service, self._create)
        self.control_srv = self.create_service(ControlJob, control_service, self._control)
        # Periodic status snapshot so a Bridge started later can still learn jobs.
        # TEAM_SYNC(Bridge): agree on QoS / stale-state policy before production.
        self.status_timer = self.create_timer(1.0, self._publish_all)
        if simulation:
            self.sim_timer = self.create_timer(sim_period, self._simulation_tick)
        self.get_logger().warning(
            'SIMULATION ONLY; NO ROBOT COMMANDS' if simulation else
            'CONTROLLER NOT CONNECTED; jobs will stay QUEUED until trusted controller integration'
        )
        if self.engine.recovered_jobs:
            self.get_logger().warning('RECOVERY_REQUIRED: ' + ', '.join(self.engine.recovered_jobs))
        self._publish_all()

    # [핵심 기능] 특정 작업 상태를 JobStatus Topic으로 발행
    def _publish_job(self, job_id: str):
        job = self.engine.status(job_id)
        if not job:
            return
        msg = JobStatus()
        msg.job_id = job['job_id']
        msg.state = job['state']
        msg.completed_strokes = job['completed_strokes']
        msg.total_strokes = job['total_strokes']
        msg.current_pen = job['current_pen']
        msg.error_code = job['error_code']
        msg.message = job['message']
        self.publisher.publish(msg)

    # [핵심 기능] 저장된 작업 상태를 주기적으로 재발행
    def _publish_all(self):
        for job in self.engine.statuses():
            self._publish_job(job['job_id'])

    @staticmethod
    def _fill(response, result):
        response.accepted = result.accepted
        response.job_id = result.job_id
        response.state = result.state
        response.error_code = result.error_code
        response.message = result.message
        return response

    # [핵심 기능] CreateJob Service 콜백: 파일 검증·DB 등록 후 결과 회신
    def _create(self, request, response):
        result = self.engine.create_job(request.job_id, request.plan_path)
        self._publish_job(request.job_id)
        self.get_logger().info(f'create job={request.job_id} accepted={result.accepted} state={result.state} code={result.error_code}')
        return self._fill(response, result)

    # [핵심 기능] ControlJob Service 콜백: 명령 저장 및 안전한 Action 취소 요청
    def _control(self, request, response):
        result = self.engine.control_job(request.job_id, request.command, request.request_id)
        self._publish_job(request.job_id)
        self.get_logger().info(f'control job={request.job_id} cmd={request.command} accepted={result.accepted} state={result.state} code={result.error_code}')
        return self._fill(response, result)

    # [핵심 기능] 오직 시험용으로만 가상의 획 진행
    def _simulation_tick(self):
        self.engine.simulate_tick()
        self._publish_all()

    def destroy_node(self):
        self.engine.close()
        return super().destroy_node()


# [핵심 기능] 실행 진입점: 환경 변수, ROS 초기화, spin 및 종료 처리
def main(args=None):
    home = Path.home() / 'A4'
    db = env_path('ART_JOB_DB', home / 'data' / 'jobs.db')
    root = env_path('ART_JOB_PLAN_ROOT', home / 'data' / 'jobs')
    simulation = os.environ.get('ART_JOB_SIMULATE', '0').strip() == '1'
    sim_period = float(os.environ.get('ART_JOB_SIM_PERIOD', '0.25'))
    if sim_period <= 0:
        raise ValueError('ART_JOB_SIM_PERIOD must be positive')
    db.parent.mkdir(parents=True, exist_ok=True)
    # Only one JobManager may control a given SQLite database at a time.
    # Separate mock/real manager process must also not serve same ROS names.
    lock_file = db.with_name(db.name + '.lock')
    with lock_file.open('a+') as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f'Another JobManager already holds {lock_file}') from exc
        rclpy.init(args=args)
        node = None
        try:
            node = JobManagerNode(db_path=db, plan_root=root, simulation=simulation, sim_period=sim_period)
            rclpy.spin(node)
        except KeyboardInterrupt:
            pass
        finally:
            if node is not None:
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()


if __name__ == '__main__':
    main()
