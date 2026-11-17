"""실물 안전 검증 전에는 모든 물리 실행 Goal을 거절합니다."""
import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, GoalResponse
from art.action import ExecuteDrawing
from .doosan_adapter import DoosanAdapter

class DrawingNode(Node):
    def __init__(self):
        super().__init__('drawing_controller')
        self.adapter = DoosanAdapter()
        self.server = ActionServer(self, ExecuteDrawing, '/art/execute_drawing',
            execute_callback=self.execute, goal_callback=self.goal)

    def goal(self, request):
        self.get_logger().error('실물 M0609/RG2 안전 검증 및 캘리브레이션이 없어 실행을 거절합니다.')
        return GoalResponse.REJECT

    def execute(self, handle):
        # 방어적 실패 경로: 안전 확인을 꾸며내지 않습니다.
        result = ExecuteDrawing.Result()
        result.success = False
        result.final_state = 'FAILED'
        result.pen_up_confirmed = False
        result.error_code = 'HARDWARE_NOT_VALIDATED'
        handle.abort()
        return result

def main(args=None):
    rclpy.init(args=args)
    node = DrawingNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
