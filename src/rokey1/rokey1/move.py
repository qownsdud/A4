import rclpy
import DR_init

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"

# Joint 이동과 Linear 이동의 최적 속도를 분리 설정
J_VEL, J_ACC = 100, 100      # deg/s, deg/s^2
L_VEL, L_ACC = 300, 300   # mm/s, mm/s^2
CYCLE = 3

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


def main(args=None):
    rclpy.init(args=args)
    node = rclpy.create_node("rokey_move", namespace=ROBOT_ID)
    DR_init.__dsr__node = node

    try:
        from DSR_ROBOT2 import (
            set_tool,
            set_tcp,
            movej,
            movel,
        )
        from DR_common2 import posx, posj
    except ImportError as e:
        node.get_logger().info(f"Error importing DSR_ROBOT2 : {e}")
        return

    # 가상 모드(sodvir)에서는 미등록 Tool/TCP 호출 시 대기할 수 있으므로 주석 처리
    # (실제 로봇 TP에 동일 이름으로 등록 후 사용 시 주석 해제)
    set_tool("Tool_Weight")
    set_tcp("GripperDA_v1")

    homej = posj([0.0, 0.0, 90.0, 0.0, 90.0, 0.0])
    posj1 = posj([0.0, 0.0, 90.0, 0.0, 30.0, 0.0])
    posj2 = posj([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    posj3 = posj([0.0, 0.0, -90.0, 0.0, 0.0, 0.0])
    posj4 = posj([0.0, -90.0, 0.0, 0.0, 0.0, 0.0])

    posx1 = posx([350.0, 34.5, 350.0, 45.0, 180.0, 45.0])
    posx2 = posx([350.0, 34.5, 300.0, 45.0, 180.0, 45.0])

    try:
        movej(homej, vel=J_VEL, acc=J_ACC)

        movej(posj2, vel=J_VEL, acc=J_ACC)

        for i in range(CYCLE):
            node.get_logger().info(f"Cycle {i+1}")

            node.get_logger().info(f"Moving to joint position: {posj1}")
            movej(posj1, vel=J_VEL, acc=J_ACC)

            node.get_logger().info(f"Moving to task position: {posx1}")
            movel(posx1, vel=L_VEL, acc=L_ACC)

            node.get_logger().info(f"Moving to task position: {posx2}")
            movel(posx2, vel=L_VEL, acc=L_ACC)

        # 정상 완료 시에만 홈 위치로 복귀
        node.get_logger().info("Returning to home position...")

        movej(posj3, vel=J_VEL, acc=J_ACC)
        movej(posj4, vel=J_VEL, acc=J_ACC)
        movej(posj2, vel=J_VEL, acc=J_ACC)
        movej(homej, vel=J_VEL, acc=J_ACC)


    except KeyboardInterrupt:
        node.get_logger().info("Program Stopped by User")

    except Exception as e:
        node.get_logger().info(f"Robot Error: {e}")

    finally:
        # Ctrl+C 종료 시 블로킹 방지를 위해 노드 정리만 수행
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()