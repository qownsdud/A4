"""중복 서버에 로컬 경로나 물리 실행 Goal을 보내지 않는지 검사합니다."""
import asyncio
import os
import time
import pytest
rclpy=pytest.importorskip('rclpy')
pytest.importorskip('art_interfaces.action')
from rclpy.node import Node
from rclpy.action import ActionServer
from art_interfaces.action import PrepareArtwork,ExecuteDrawing
from art_kiosk_bridge.bridge_node import KioskBridgeNode
from art_kiosk_bridge.schemas import PrepareArtworkBody
from art_kiosk_bridge.errors import ServiceUnavailable
from art_job_manager.job_manager_node import RealJobManagerNode
from art_artwork_pipeline.path_planner.drawing_plan import build_plan,write_job_plan


def test_duplicate_pipeline_never_receives_local_file_path():
    if os.environ.get('ROS_DOMAIN_ID') not in ('97','99'):pytest.skip('격리 도메인이 필요합니다.')
    rclpy.init();nodes=[Node('pipeline_duplicate_one'),Node('pipeline_duplicate_two')]
    servers=[ActionServer(node,PrepareArtwork,'/duplicate_check/prepare_artwork',lambda handle:PrepareArtwork.Result()) for node in nodes]
    bridge=KioskBridgeNode(artwork_action="/duplicate_check/prepare_artwork")
    try:
        deadline=time.monotonic()+4
        while bridge._artwork_server_count()!=2 and time.monotonic()<deadline:rclpy.spin_once(bridge,timeout_sec=.05)
        assert bridge._artwork_server_count()==2
        body=PrepareArtworkBody(job_id='DUP',stage='LINEART',input_path='/tmp/nonexistent/photo.png')
        with pytest.raises(ServiceUnavailable,match='중복'):
            asyncio.run(bridge.prepare_artwork(body))
    finally:
        bridge.destroy_node()
        for server in servers:server.destroy()
        for node in nodes:node.destroy_node()
        rclpy.shutdown()


def test_duplicate_controller_keeps_job_queued_without_goal(tmp_path):
    if os.environ.get('ROS_DOMAIN_ID') not in ('97','99'):pytest.skip('격리 도메인이 필요합니다.')
    rclpy.init();nodes=[Node('controller_duplicate_one'),Node('controller_duplicate_two')]
    servers=[ActionServer(node,ExecuteDrawing,'/duplicate_check/execute_drawing',lambda handle:ExecuteDrawing.Result()) for node in nodes]
    manager=RealJobManagerNode(db_path=tmp_path/'jobs.db',plan_root=tmp_path,action_name='/duplicate_check/execute_drawing')
    try:
        deadline=time.monotonic()+4
        while manager._controller_server_count()!=2 and time.monotonic()<deadline:rclpy.spin_once(manager,timeout_sec=.05)
        assert manager._controller_server_count()==2
        plan=build_plan([{'points':[[0,0],[10,10]]}],20,20,job_id='DUP')
        path=write_job_plan(plan,tmp_path)
        assert manager.engine.create_job('DUP',str(path)).accepted
        manager._poll()
        assert manager.engine.status('DUP')['state']=='QUEUED'
        assert manager._active_job_id is None
    finally:
        manager.destroy_node()
        for server in servers:server.destroy()
        for node in nodes:node.destroy_node()
        rclpy.shutdown()
