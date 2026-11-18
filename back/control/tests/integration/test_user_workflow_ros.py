"""격리된 ROS_DOMAIN_ID에서 Pipeline → 실제 JobManager → Fake Action을 검증합니다."""
import asyncio
import importlib.util
import json
from pathlib import Path
import threading
import time
import io
import httpx
import pytest
from PIL import Image,ImageDraw
rclpy=pytest.importorskip('rclpy')
pytest.importorskip('art_interfaces.action')
from rclpy.executors import MultiThreadedExecutor
from rclpy.action import ActionClient
from art_interfaces.action import ExecuteDrawing
from art_artwork_pipeline.pipeline_node import PipelineNode
from art_kiosk_bridge.bridge_node import KioskBridgeNode
from art_kiosk_bridge.http_api import create_app
from art_job_manager.job_manager_node import RealJobManagerNode
from art_drawing_controller.drawing_node import DrawingNode
from art_kiosk import server

def test_user_one_click_real_ros_pipeline_and_fake_controller(monkeypatch,tmp_path):
    import os
    if os.environ.get('ROS_DOMAIN_ID') not in ('97', '99'):
        pytest.skip('실물과 분리된 ROS_DOMAIN_ID=97 또는 99에서만 실행합니다.')
    monkeypatch.setenv('ART_JOB_PLAN_ROOT',str(tmp_path))
    monkeypatch.setenv('ART_LINEART_METHOD','cv')
    monkeypatch.setenv('A4_FAKE_STROKE_SECONDS','0.35')
    monkeypatch.delenv('ART_ADMIN_TOKEN', raising=False)
    spec=importlib.util.spec_from_file_location('fake_controller_test_only',Path(__file__).parents[1]/'job_manager_v1/fake_drawing_controller.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rclpy.init()
    pipeline=PipelineNode()
    bridge=KioskBridgeNode()
    manager=RealJobManagerNode(db_path=tmp_path/'jobs.db',plan_root=tmp_path)
    fake=module.FakeController()
    executor=MultiThreadedExecutor(num_threads=6)
    nodes=[pipeline,bridge,manager,fake]
    for node in nodes: executor.add_node(node)
    worker=threading.Thread(target=executor.spin,daemon=True)
    worker.start()
    monkeypatch.setattr(server.app.state,'bridge_transport',httpx.ASGITransport(app=create_app(bridge)),raising=False)
    async def run():
        for _ in range(150):
            if bridge.is_ready() and bridge._artwork.server_is_ready(): break
            await asyncio.sleep(.02)
        assert bridge.is_ready() and bridge._artwork.server_is_ready()
        image=Image.new('RGB',(80,110),'white')
        ImageDraw.Draw(image).ellipse((15,15,65,90),outline='black',width=2)
        buffer=io.BytesIO();image.save(buffer,'PNG')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://kiosk.test') as client:
            # DDS 발견 직후의 일시적인 ready 변동을 피하고 격리 연결을 확인합니다.
            await asyncio.sleep(.5)
            response=await client.post('/api/kiosk/prepare',files={'photo':('photo.png',buffer.getvalue())},data={'text':'Hi'})
            assert response.status_code==200,response.text
            prepared=response.json();job=prepared['job_id']
            assert manager.engine.status(job) is None
            response=await client.get('/api/kiosk/preview',headers={'X-Preview-Ticket':prepared['ticket']})
            assert response.status_code==200 and 'data-layer="calligraphy"' in response.text
            response=await client.post('/api/kiosk/draw',json={'ticket':prepared['ticket']})
            assert response.status_code==202,response.text
            repeated=await client.post('/api/kiosk/draw',json={'ticket':prepared['ticket']})
            assert repeated.status_code==202
            assert len(manager.engine.statuses())==1
            # 가로 배치·문구가 늘린 획 수에 맞춰 모의 실행 완료를 기다립니다.
            total=manager.engine.status(job)['total_strokes']
            deadline=time.monotonic()+max(15.,total*.7+5.)
            while time.monotonic()<deadline:
                current=await client.get('/api/kiosk/current')
                assert current.status_code==200,current.text
                assert current.json()['job_id']==job and current.json()['text']=='Hi'
                status=bridge.get_status(job)
                if status and status.state=='COMPLETED':
                    assert status.completed_strokes==status.total_strokes
                    return
                await asyncio.sleep(.02)
            pytest.fail(str(manager.engine.status(job)))
    try:
        asyncio.run(run())
    finally:
        executor.shutdown(timeout_sec=5)
        worker.join(timeout=5)
        for node in nodes:
            executor.remove_node(node)
            node.destroy_node()
        manager.engine.close()
        rclpy.shutdown()
