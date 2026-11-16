
import argparse

import rclpy
from rclpy.node import Node

from dsr_msgs2.srv import (
    GetCurrentTcp,
    GetCurrentPosj,
    GetCurrentPosx,
    MoveJoint,
    MoveLine,
)

PREFIX = "/dsr01/dsr_controller2"

# 초기 관절 자세 (degree)
HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]

# 상대 이동량 (mm)
# X, Y, Z, A, B, C
MOVE_OFFSET = [
    0.0, 0.0, -94,
    0.0, 0.0, 0.0
]


class MoveTest(Node):

    def __init__(self):
        super().__init__("move_test")

        self.tcp_client = self.create_client(
            GetCurrentTcp,
            f"{PREFIX}/tcp/get_current_tcp"
        )

        self.joint_client = self.create_client(
            GetCurrentPosj,
            f"{PREFIX}/aux_control/get_current_posj"
        )

        self.pos_client = self.create_client(
            GetCurrentPosx,
            f"{PREFIX}/aux_control/get_current_posx"
        )

        self.home_client = self.create_client(
            MoveJoint,
            f"{PREFIX}/motion/move_joint"
        )

        self.move_client = self.create_client(
            MoveLine,
            f"{PREFIX}/motion/move_line"
        )

    def call_service(self, client, request, timeout=30.0):

        if not client.wait_for_service(timeout_sec=5.0):
            raise RuntimeError("서비스 연결 실패")

        future = client.call_async(request)

        rclpy.spin_until_future_complete(
            self, future, timeout_sec=timeout
        )

        if not future.done():
            raise TimeoutError(
                "서비스 응답 시간 초과. 로봇 상태를 확인하세요."
            )

        result = future.result()

        if result is None:
            raise RuntimeError("서비스 호출 실패")

        return result

    def check_tcp(self):

        result = self.call_service(
            self.tcp_client,
            GetCurrentTcp.Request()
        )

        if not result.success or result.info != "PenGripper":
            raise RuntimeError(
                f"TCP 불일치: {result.info}"
            )

        print(f"활성 TCP: {result.info}")

    def get_joint_position(self):

        result = self.call_service(
            self.joint_client,
            GetCurrentPosj.Request()
        )

        if not result.success:
            raise RuntimeError("관절 위치 조회 실패")

        return list(result.pos)

    def get_position(self):

        request = GetCurrentPosx.Request()
        request.ref = 0  # BASE

        result = self.call_service(
            self.pos_client, request
        )

        if not result.success:
            raise RuntimeError("TCP 좌표 조회 실패")

        return list(result.task_pos_info[0].data[:6])

    def move_home(self):

        req = MoveJoint.Request()

        req.pos = HOME_JOINTS.copy()
        req.vel = 5.0
        req.acc = 10.0
        req.time = 0.0
        req.radius = 0.0
        req.mode = 0
        req.blend_type = 0
        req.sync_type = 0

        print("\n[HOME 복귀]")
        print("목표 관절:", req.pos)

        result = self.call_service(
            self.home_client,
            req,
            timeout=120.0
        )

        if not result.success:
            raise RuntimeError("HOME 이동 실패")

        joints = self.get_joint_position()

        print("이동 후 관절:", joints)

        tolerance = 0.5  # degree

        for current, target in zip(joints, HOME_JOINTS):
            if abs(current - target) > tolerance:
                raise RuntimeError(
                    "HOME 목표 관절과 현재 관절이 일치하지 않음"
                )

        print("HOME 복귀 확인 완료")

    def run(self, execute=False):

        # 1. TCP 확인
        self.check_tcp()

        # 2. HOME 복귀
        print("\n초기 HOME 자세:", HOME_JOINTS)

        if not execute:
            print("DRY RUN: HOME 이동 명령 전송 안 함")
        else:
            # HOME 입력 없이 자동 실행
            self.move_home()

        # 3. 현재 TCP 좌표 확인
        pos = self.get_position()

        print("\n현재 TCP 좌표:", pos)

        # 4. 상대 이동 설정
        req = MoveLine.Request()

        req.pos = MOVE_OFFSET.copy()
        req.vel = [10.0, 0.0]
        req.acc = [15.0, 0.0]

        req.time = 0.0
        req.radius = 0.0
        req.ref = 0
        req.mode = 1
        req.blend_type = 0
        req.sync_type = 0

        print(
            f"\n목표 이동: BASE "
            f"X {req.pos[0]:+g}mm, "
            f"Y {req.pos[1]:+g}mm, "
            f"Z {req.pos[2]:+g}mm"
        )

        target = [
            pos[i] + req.pos[i] for i in range(3)
        ]

        print(
            f"예상 목표 위치: "
            f"X={target[0]:.3f}, "
            f"Y={target[1]:.3f}, "
            f"Z={target[2]:.3f}"
        )

        # 5. DRY RUN
        if not execute:
            print("\nDRY RUN 완료: 실제 이동 없음")
            return

        # 6. 상대 이동 승인
        confirmation = input(
            "\n상대 이동 경로 확인 후 MOVE 입력: "
        )

        if confirmation != "MOVE":
            print("상대 이동 취소")
            return

        print("\n이동 요청 전송")

        result = self.call_service(
            self.move_client,
            req,
            timeout=60.0
        )

        if not result.success:
            raise RuntimeError("상대 이동 실패")

        # 7. 이동 후 좌표 확인
        after = self.get_position()

        print("\n[이동 완료]")
        print("이동 후 TCP 좌표:", after)

        print(
            f"실제 이동량: "
            f"X {after[0] - pos[0]:+.3f}mm, "
            f"Y {after[1] - pos[1]:+.3f}mm, "
            f"Z {after[2] - pos[2]:+.3f}mm"
        )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 HOME 복귀 및 상대 이동 허용"
    )

    args = parser.parse_args()

    rclpy.init()
    node = MoveTest()

    try:
        node.run(execute=args.execute)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
