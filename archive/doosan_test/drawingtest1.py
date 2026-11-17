import rclpy
import DR_init
import time

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"

# Joint 이동과 Linear 이동의 최적 속도를 분리 설정
J_VEL, J_ACC = 60, 60      # deg/s, deg/s^2
L_VEL, L_ACC = 100, 100   # mm/s, mm/s^2
CYCLE = 3

ON, OFF = 1, 0

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

up = [0.00, 0.00, 48.00, 0.00, 0.00, 0.00]    
down = [0.00, 0.00, -48.00, 0.00, 0.00, 0.00]
# lastdown = [0.00, 0.00, -34.50, 0.00, 0.00, 0.00]
lastdown = [0.00, 0.00, -28.00, 0.00, 0.00, 0.00]
mv = [0.00, 300.00, 0.00, 0.00, 0.00, 0.00]

rclpy.init(args=None)
node = rclpy.create_node("rokey_gear", namespace=ROBOT_ID)
DR_init.__dsr__node = node

try:
    from DSR_ROBOT2 import (
        set_tool,
        set_tcp,
        movej,
        movel,
        amovel,
        move_periodic,
        amove_periodic,
        task_compliance_ctrl,
        set_stiffnessx,
        release_compliance_ctrl,
        set_desired_force,
        release_force,
        set_digital_output,
        DR_MV_MOD_REL,
        DR_MV_MOD_ABS,
        DR_FC_MOD_REL,
        DR_FC_MOD_ABS,
        DR_TOOL,
    )
    from DR_common2 import posx, posj
except ImportError as e:
    node.get_logger().info(f"Error importing DSR_ROBOT2 : {e}")

def main():
    set_tool("Tool_Weight")
    set_tcp("GripperDA_v1")

    homej = posj([0.0, 0.0, 90.0, 0.0, 90.0, 0.0])
    p1x = posx([0, 0, 0, 0, 0, 0])

    movej(homej, vel=J_VEL, acc=J_ACC)

    task_compliance_ctrl()
    set_stiffnessx([3000.0, 3000.0, 3000.0, 200.0, 200.0, 200.0], time=0.3)
    set_desired_force([0.0, 0.0, -20.0, 0.0, 0.0, 0.0], dir=[0, 0, 1, 0, 0, 0], time=0.3, mod=DR_FC_MOD_REL)
    release_force()
    release_compliance_ctrl()