"""ROS Action의 동시 요청 거절과 취소 정책 시험."""
import os
import threading
import time
import pytest
rclpy=pytest.importorskip('rclpy')
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from art_interfaces.action import PrepareArtwork
from art_artwork_pipeline import pipeline_node

def test_busy_rejection_and_cancellation(monkeypatch):
    if os.environ.get('ROS_DOMAIN_ID') not in ('97', '99'):
        pytest.skip('격리 도메인 97 또는 99 필요')
    started=threading.Event()
    def processing(job_id, **kwargs):
        started.set()
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            if kwargs['cancel']():
                raise InterruptedError('모의 처리 취소')
            time.sleep(.01)
        raise RuntimeError('취소 요청을 받지 못했습니다.')
    monkeypatch.setattr(pipeline_node,'prepare_artwork',processing)
    rclpy.init()
    server=pipeline_node.PipelineNode()
    node=rclpy.create_node('pipeline_policy_client')
    client=ActionClient(node,PrepareArtwork,'/art/prepare_artwork')
    executor=MultiThreadedExecutor(num_threads=4)
    executor.add_node(server);executor.add_node(node)
    thread=threading.Thread(target=executor.spin,daemon=True);thread.start()
    def wait(future):
        deadline=time.monotonic()+4
        while not future.done() and time.monotonic()<deadline:
            time.sleep(.01)
        assert future.done()
        return future.result()
    try:
        assert client.wait_for_server(timeout_sec=3)
        goal=PrepareArtwork.Goal();goal.job_id='POLICY';goal.stage='LINEART'
        handle=wait(client.send_goal_async(goal))
        assert handle.accepted and started.wait(2)
        assert not wait(client.send_goal_async(goal)).accepted
        wait(handle.cancel_goal_async())
        result=wait(handle.get_result_async())
        assert not result.result.success and result.result.error_code=='CANCELED'
        assert not server._busy.locked()
    finally:
        executor.shutdown(timeout_sec=5);thread.join(timeout=5)
        client.destroy();node.destroy_node();server.destroy_node();rclpy.shutdown()
