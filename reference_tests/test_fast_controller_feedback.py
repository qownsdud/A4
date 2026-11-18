"""빠른 Fake 피드백을 실제 DDS로 전달해 체크포인트 누락 여부를 확인합니다."""
import importlib.util
import os
from pathlib import Path
import threading
import time
import pytest
rclpy = pytest.importorskip('rclpy')
pytest.importorskip('art_interfaces.action')
from rclpy.executors import MultiThreadedExecutor
from art_job_manager.job_manager_node import RealJobManagerNode
from art_artwork_pipeline.path_planner.drawing_plan import build_plan, write_job_plan

@pytest.mark.parametrize('stroke_seconds', ['0.001', '0.01'])
def test_fast_feedback_keeps_all_checkpoints(tmp_path, monkeypatch, stroke_seconds):
    if os.environ.get('ROS_DOMAIN_ID') not in ('97', '99'):
        pytest.skip('실물과 분리된 ROS_DOMAIN_ID=97 또는 99가 필요합니다.')
    monkeypatch.setenv('A4_FAKE_STROKE_SECONDS', stroke_seconds)
    spec = importlib.util.spec_from_file_location('fast_fake', Path(__file__).parents[1]/'job_manager_v1/fake_drawing_controller.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rclpy.init()
    manager = RealJobManagerNode(db_path=tmp_path/'jobs.db', plan_root=tmp_path)
    fake = module.FakeController()
    executor = MultiThreadedExecutor(num_threads=4)
    for node in (manager, fake):
        executor.add_node(node)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    try:
        paths = [{'points': [[x*10,y*10], [x*10+2,y*10+2]]} for x in range(10) for y in range(6)]
        plan = build_plan(paths, 100, 60, job_id='FAST')
        path = write_job_plan(plan, tmp_path)
        assert manager.engine.create_job('FAST', str(path)).accepted
        deadline = time.monotonic()+15
        while time.monotonic()<deadline:
            state = manager.engine.status('FAST')
            if state['state'] in ('COMPLETED','RECOVERY_REQUIRED'):
                break
            time.sleep(.01)
        assert state['state'] == 'COMPLETED', state
        assert state['completed_strokes'] == state['total_strokes'] == 60
    finally:
        executor.shutdown(timeout_sec=3)
        thread.join(timeout=3)
        for node in (manager, fake):
            executor.remove_node(node)
            node.destroy_node()
        rclpy.shutdown()
