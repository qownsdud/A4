"""한 번에 하나의 이미지 작업을 수락하는 ROS2 Action 서버."""
import threading
import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, GoalResponse, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from art.action import PrepareArtwork
from .pipeline_runner import prepare_artwork

class PipelineNode(Node):
    def __init__(self):
        super().__init__('artwork_pipeline')
        self._busy = threading.Lock()
        self.server = ActionServer(self, PrepareArtwork, '/art/prepare_artwork',
            execute_callback=self.execute, goal_callback=self.goal,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=ReentrantCallbackGroup())

    def goal(self, request):
        if request.stage not in ('LINEART','PLAN') or not self._busy.acquire(blocking=False):
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def execute(self, handle):
        result = PrepareArtwork.Result()
        request = handle.request
        result.job_id = request.job_id
        def feedback(stage):
            message = PrepareArtwork.Feedback()
            message.stage = stage
            message.message = '이미지 처리 중'
            handle.publish_feedback(message)
        try:
            paths = prepare_artwork(request.job_id,stage=request.stage,input_path=request.input_path,
                method=request.method,paper=request.paper,detail=request.detail,seed=request.seed,
                text=request.text,cancel=lambda: handle.is_cancel_requested,feedback=feedback)
            for key,value in paths.items():
                setattr(result,key,value)
            result.success = True
            handle.succeed()
        except InterruptedError as exc:
            result.error_code = 'CANCELED'
            result.message = str(exc)
            handle.canceled()
        except Exception as exc:
            result.error_code = type(exc).__name__
            result.message = str(exc)[:300]
            handle.abort()
        finally:
            self._busy.release()
        return result

def main(args=None):
    rclpy.init(args=args)
    node = PipelineNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
