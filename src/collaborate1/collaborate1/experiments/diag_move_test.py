"""로봇 컨트롤러 연결, Tool/TCP 설정, 첫 movej 동작 여부를 단계별 로그로 진단하는 테스트 노드."""

import os
import time

import rclpy
import DR_init
from dsr_msgs2.srv import (
    GetCurrentPosj,
    GetCurrentTcp,
    GetCurrentTool,
    GetRobotMode,
    GetRobotState,
)

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"
HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init(args=None)
node = rclpy.create_node("diag_move_test", namespace=ROBOT_ID)
DR_init.__dsr__node = node

from DSR_ROBOT2 import set_tool, set_tcp, movej  # noqa: E402
from DR_common2 import posj  # noqa: E402


def _call_srv(srv_type, srv_name: str, timeout_sec: float = 3.0):
    client = node.create_client(srv_type, srv_name)
    if not client.wait_for_service(timeout_sec=timeout_sec):
        node.get_logger().error(f"[FAIL] 서비스 응답 없음 ({timeout_sec}s): {srv_name}")
        return None
    future = client.call_async(srv_type.Request())
    rclpy.spin_until_future_complete(node, future, timeout_sec=timeout_sec)
    if not future.done():
        node.get_logger().error(f"[FAIL] 서비스 호출 타임아웃 ({timeout_sec}s): {srv_name}")
        return None
    return future.result()


def main() -> None:
    log = node.get_logger()
    try:
        log.info(
            "[STEP 1] ROS 환경변수: "
            f"ROS_DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID')}, "
            f"RMW_IMPLEMENTATION={os.environ.get('RMW_IMPLEMENTATION')}, "
            f"ROS_DISCOVERY_SERVER={os.environ.get('ROS_DISCOVERY_SERVER')}"
        )

        prefix = f"/{ROBOT_ID}/dsr_controller2"

        log.info("[STEP 2] 로봇 상태/모드 조회 중...")
        st = _call_srv(GetRobotState, f"{prefix}/system/get_robot_state")
        md = _call_srv(GetRobotMode, f"{prefix}/system/get_robot_mode")
        if st is None or md is None:
            log.error("dsr_controller2 서비스에 연결할 수 없습니다. bringup 실행 여부를 확인하세요.")
            return
        log.info(f"[STEP 2] robot_state={st.robot_state} (1=STANDBY), robot_mode={md.robot_mode} (1=AUTO)")

        log.info("[STEP 3] 현재 Tool / TCP / 관절각 조회 중...")
        cur_tool = _call_srv(GetCurrentTool, f"{prefix}/tool/get_current_tool")
        cur_tcp = _call_srv(GetCurrentTcp, f"{prefix}/tcp/get_current_tcp")
        cur_posj = _call_srv(GetCurrentPosj, f"{prefix}/aux_control/get_current_posj")
        log.info(
            f"[STEP 3] 현재 Tool={cur_tool.info if cur_tool else 'N/A'!r}, "
            f"TCP={cur_tcp.info if cur_tcp else 'N/A'!r}, "
            f"posj={[round(v, 2) for v in cur_posj.pos] if cur_posj and cur_posj.success else 'N/A'}"
        )

        log.info(f"[STEP 4] set_tool({TOOL_NAME!r}) 호출 중...")
        t0 = time.monotonic()
        ret_tool = set_tool(TOOL_NAME)
        log.info(f"[STEP 4] set_tool 결과: ret={ret_tool} ({time.monotonic() - t0:.2f}s)")

        log.info(f"[STEP 5] set_tcp({TCP_NAME!r}) 호출 중...")
        t0 = time.monotonic()
        ret_tcp = set_tcp(TCP_NAME)
        log.info(f"[STEP 5] set_tcp 결과: ret={ret_tcp} ({time.monotonic() - t0:.2f}s)")

        after_tool = _call_srv(GetCurrentTool, f"{prefix}/tool/get_current_tool")
        after_tcp = _call_srv(GetCurrentTcp, f"{prefix}/tcp/get_current_tcp")
        log.info(
            f"[STEP 5-1] 설정 후 Tool={after_tool.info if after_tool else 'N/A'!r}, "
            f"TCP={after_tcp.info if after_tcp else 'N/A'!r}"
        )

        log.info(f"[STEP 6] movej({HOME_JOINTS}, vel=20, acc=20) 호출 중...")
        t0 = time.monotonic()
        ret_move = movej(posj(HOME_JOINTS), vel=20, acc=20)
        log.info(f"[STEP 6] movej 완료: ret={ret_move} ({time.monotonic() - t0:.2f}s)")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
