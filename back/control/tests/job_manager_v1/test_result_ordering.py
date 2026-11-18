"""실제 상태 엔진으로 Result와 Feedback 도착 순서 및 누락을 검증합니다."""
from concurrent.futures import Future
from types import SimpleNamespace
from pathlib import Path
import json
import pytest

pytest.importorskip('rclpy')
pytest.importorskip('art_interfaces.action')
import rclpy
from art_job_manager.job_manager_node import RealJobManagerNode
from art_artwork_pipeline.path_planner.drawing_plan import build_plan, write_job_plan

@pytest.fixture
def node(tmp_path):
    rclpy.init()
    item = RealJobManagerNode(db_path=tmp_path/'jobs.db', plan_root=tmp_path)
    plan = build_plan([{'points': [[0, 0], [10, 10]]}], 20, 20, job_id='ORDER')
    path = write_job_plan(plan, tmp_path)
    assert item.engine.create_job('ORDER', str(path)).accepted
    assert item.engine.prepare_dispatch('ORDER')
    item._active_job_id = 'ORDER'
    yield item
    item.destroy_node()
    rclpy.shutdown()

def result(node):
    count = node.engine.status('ORDER')['total_strokes']
    future = Future()
    future.set_result(SimpleNamespace(status=4, result=SimpleNamespace(
        success=True, final_state='COMPLETED', completed_strokes=count,
        pen_up_confirmed=True, error_code='', message='')))
    node._on_result('ORDER', future)

def feedback(node, event, stroke_id=0, pen_id='', pen_up=False):
    node._on_feedback('ORDER', SimpleNamespace(feedback=SimpleNamespace(
        event=event, stroke_id=stroke_id, pen_id=pen_id, pen_up_confirmed=pen_up)))

def test_result_before_feedback_waits_for_observed_checkpoints(node):
    result(node)
    assert node.engine.status('ORDER')['state'] == 'DISPATCHING'
    feedback(node, 'STARTED')
    # 실행 순서와 펜은 저장된 실제 계획에서 읽습니다.
    plan = json.loads(Path(node.engine.status('ORDER')['plan_path']).read_text())
    for stroke in plan['strokes']:
        feedback(node, 'STROKE_STARTED', stroke['stroke_id'], stroke['pen_id'])
        feedback(node, 'STROKE_COMPLETED', stroke['stroke_id'], stroke['pen_id'], True)
    assert node.engine.status('ORDER')['state'] == 'COMPLETED'
    assert node._active_job_id is None

def test_missing_feedback_is_never_invented(node):
    result(node)
    job, out, _ = node._pending_result
    node._pending_result = (job, out, 0.)
    node._finish_pending_result()
    assert node.engine.status('ORDER')['state'] == 'RECOVERY_REQUIRED'
    assert node.engine.status('ORDER')['completed_strokes'] == 0

def test_legacy_controller_pause_does_not_cancel_partial_stroke(node):
    from art_interfaces.srv import ControlJob
    feedback(node,'STARTED')
    request=ControlJob.Request(job_id='ORDER',command='PAUSE',request_id='legacy-pause')
    reply=node._control(request,ControlJob.Response())
    assert reply.accepted is False
    assert reply.error_code=='CONTINUOUS_PAUSE_UNSUPPORTED'
    assert node.engine.status('ORDER')['state']=='DRAWING'
    assert node._cancel_requested is False
