import rclpy
import DR_init
import time

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"

# Joint 이동과 Linear 이동의 최적 속도를 분리 설정
J_VEL, J_ACC = 60, 60      # deg/s, deg/s^2
L_VEL, L_ACC = 500, 500   # mm/s, mm/s^2
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
        DR_FC_MOD_REL,
        DR_FC_MOD_ABS,
        DR_TOOL,
    )
    from DR_common2 import posx, posj
except ImportError as e:
    node.get_logger().info(f"Error importing DSR_ROBOT2 : {e}")

def grasp(t):
    set_digital_output(2, OFF)
    set_digital_output(1, OFF)
    set_digital_output(1, ON)
    set_digital_output(2, OFF)
    time.sleep(t)

def release(t):
    set_digital_output(2, OFF)
    set_digital_output(1, OFF)
    set_digital_output(1, OFF)
    set_digital_output(2, ON)
    time.sleep(t)

def deliever_gear():
    movel(down, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
    grasp(0.5)
    movel(up, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
    movel(mv, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
    movel(down, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
    release(0.2)
    movel(up, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

def deliever_lastgear():
    movel(down, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
    grasp(0.5)
    movel(up, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
    movel(mv, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
    movel(lastdown, vel=100, acc=100, mod=DR_MV_MOD_REL)

    # COMPLIANCE ON 0.5초
    # FORCE ON z-20N, 0.5초
    task_compliance_ctrl()
    set_stiffnessx([3000.0, 3000.0, 3000.0, 200.0, 200.0, 200.0], time=0.3)
    set_desired_force([0.0, 0.0, -20.0, 0.0, 0.0, 0.0], dir=[0, 0, 1, 0, 0, 0], time=0.3, mod=DR_FC_MOD_REL)
    # PERIODIC c10도, 주기1초, DR_TOOL기준, 3회반복
    move_periodic(amp=[0.00, 0.00, 0.00, 0.00, 0.00, 10.00], period=[0.00, 0.00, 0.00, 0.00, 0.00, 1.00], repeat=2, ref=DR_TOOL)
    # movel([0.00, 0.00, -10.00, 0.00, 0.00, 0.00], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
    # FORCE OFF
    # COMPLIANCE OFF
    release_force()
    release_compliance_ctrl()
    release(0.2)
    movel(up, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

def main():
    set_tool("Tool_Weight")
    set_tcp("GripperDA_v1")

    homej = posj([0.0, 0.0, 90.0, 0.0, 90.0, 0.0])
    p1x = posx([364.07, -155.36, 100.00, 133.04, 178.51, 133.66])
    p2x = posx([458.24, -201.39, 100.00, 134.50, 177.94, 135.08])
    p3x = posx([450.67, -96.72, 100.00, 135.60, 179.16, 136.19])
    p0x = posx([424.05, -151.23, 100.00, 141.02, 177.47, 141.37])

    movej(homej, vel=J_VEL, acc=J_ACC)
    release(0.2)
    set_digital_output(1, OFF)
    set_digital_output(2, OFF)

    movel(p1x, vel=L_VEL, acc=L_ACC)
    deliever_gear()
    movel(p3x, vel=L_VEL, acc=L_ACC)
    deliever_gear()
    movel(p2x, vel=L_VEL, acc=L_ACC)
    deliever_gear()
    movel(p0x, vel=L_VEL, acc=L_ACC)
    deliever_lastgear()

    movej(homej, vel=J_VEL, acc=J_ACC)