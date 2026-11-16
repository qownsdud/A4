"""저장된 3개 펜 위치(~/.ros/pen_slots.json)를 불러와 자동 픽앤플레이스를 수행하는 노드.

동작 순서 (1~3번 펜 반복):
- 그리퍼 열기 -> 펜 위 +100 mm 접근 -> 하강 -> 펜 집기(1 ON, 2 OFF) -> +100 mm 상승
- 홈 위치 이동 및 대기
- 다시 펜 위 +100 mm 접근 -> 하강 -> 펜 놓기(1 OFF, 2 ON) -> +100 mm 상승
"""

import json
import os
import time
from typing import List

import rclpy
import DR_init

from collaborate1.core.run_logger import RunLogSession

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"

HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
J_VEL, J_ACC = 60, 60
L_VEL, L_ACC = 80, 80            # 공중 이동 속도
PICK_VEL, PICK_ACC = 25, 25      # 하강/상승(집기·놓기) 속도
APPROACH_OFFSET_Z = 100.0        # 펜 위 대기/진입 높이 오프셋 (mm)
NUM_SLOTS = 3
ON, OFF = 1, 0
SLOTS_FILE = os.path.expanduser("~/.ros/pen_slots.json")

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init(args=None)
node = rclpy.create_node("pen_pick_place", namespace=ROBOT_ID)
DR_init.__dsr__node = node

try:
    from DSR_ROBOT2 import (
        set_tool,
        set_tcp,
        movej,
        movel,
        set_digital_output,
        DR_MV_MOD_ABS,
    )
    from DR_common2 import posx, posj
except ImportError as e:
    node.get_logger().error(f"Error importing DSR_ROBOT2: {e}")
    raise


def set_gripper_state(pin1: int, pin2: int, label: str) -> None:
    """디지털 출력 1, 2번 핀으로 그리퍼 상태를 설정한다."""
    set_digital_output(1, OFF)
    set_digital_output(2, OFF)
    if pin1 != OFF or pin2 != OFF:
        set_digital_output(1, pin1)
        set_digital_output(2, pin2)
    time.sleep(0.5)
    node.get_logger().info(f"그리퍼: {label} (DO1={pin1}, DO2={pin2})")


def load_slots(path: str = SLOTS_FILE) -> List[List[float]]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"저장된 펜 위치 파일({path})이 없습니다. 먼저 'ros2 run collaborate1 teach_pen_slots'로 3개 위치를 지정하세요."
        )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or len(data) != NUM_SLOTS:
        raise ValueError(f"펜 위치 개수가 {NUM_SLOTS}개가 아닙니다: {path}")
    return [[float(v) for v in p[:6]] for p in data]


def run_pick_home_return(slot_idx: int, pick_pose: List[float]) -> None:
    """지정된 펜을 위 +50mm 접근 -> 집기 -> 홈 이동 -> 다시 원위치에 내려놓는다."""
    x, y, z, rx, ry, rz = pick_pose
    approach = posx([x, y, z + APPROACH_OFFSET_Z, rx, ry, rz])
    target = posx([x, y, z, rx, ry, rz])
    homej = posj(HOME_JOINTS)

    node.get_logger().info(f"=== [펜 {slot_idx}] 집기 시작 ===")
    set_gripper_state(OFF, ON, "놓기")
    movel(approach, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
    movel(target, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
    set_gripper_state(ON, OFF, "잡기")
    movel(approach, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)

    node.get_logger().info(f"[펜 {slot_idx}] 홈 위치로 이동")
    movej(homej, vel=J_VEL, acc=J_ACC)
    time.sleep(1.0)

    node.get_logger().info(f"[펜 {slot_idx}] 원위치로 복귀")
    movel(approach, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_ABS)
    movel(target, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
    set_gripper_state(OFF, ON, "놓기")
    movel(approach, vel=PICK_VEL, acc=PICK_ACC, mod=DR_MV_MOD_ABS)
    node.get_logger().info(f"=== [펜 {slot_idx}] 원위치 완료 ===")


def main() -> None:
    with RunLogSession("pen_pick_place"):
        set_tool(TOOL_NAME)
        set_tcp(TCP_NAME)

        try:
            slots = load_slots()
            node.get_logger().info(f"저장된 {len(slots)}개 펜 위치 로드 완료")

            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
            for idx, pick_pose in enumerate(slots, start=1):
                run_pick_home_return(idx, pick_pose)

            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
            set_gripper_state(OFF, OFF, "기본")
            node.get_logger().info("1~3번 펜 전체 자동 픽앤플레이스 완료!")
        finally:
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
