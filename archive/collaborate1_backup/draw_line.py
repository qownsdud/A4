
import argparse
import statistics

import rclpy
from rclpy.node import Node

from dsr_msgs2.srv import (
    GetCurrentTcp,
    GetCurrentPosx,
    GetToolForce,
    MoveLine,
)

PREFIX = "/dsr01/dsr_controller2"

LINE_LENGTH = 20.0  # mm
DRAW_SPEED = 5.0
DRAW_ACC = 10.0
SAMPLE_COUNT = 10


class DrawLine(Node):

    def __init__(self):
        super().__init__("draw_line")

        self.tcp_client = self.create_client(
            GetCurrentTcp,
            f"{PREFIX}/tcp/get_current_tcp"
        )

        self.pos_client = self.create_client(
            GetCurrentPosx,
            f"{PREFIX}/aux_control/get_current_posx"
        )

        self.force_client = self.create_client(
            GetToolForce,
            f"{PREFIX}/aux_control/get_tool_force"
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
                "서비스 응답 시간 초과. 로봇 상태 확인 필요"
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
            raise RuntimeError("PenGripper TCP 불일치")

        print("TCP 확인:", result.info)

    def get_position(self):
        req = GetCurrentPosx.Request()
        req.ref = 0

        result = self.call_service(self.pos_client, req)

        if not result.success:
            raise RuntimeError("TCP 위치 조회 실패")

        return list(result.task_pos_info[0].data[:6])

    def get_fz(self):
        req = GetToolForce.Request()
        req.ref = 0

        result = self.call_service(
            self.force_client, req, timeout=5.0
        )

        if not result.success:
            raise RuntimeError("Fz 측정 실패")

        return float(result.tool_force[2])

    def measure_fz(self, label):
        values = [
            self.get_fz() for _ in range(SAMPLE_COUNT)
        ]

        mean = statistics.mean(values)

        print(f"\n[{label}]")
        print(f"평균 Fz: {mean:+.3f} N")
        print(f"최소 Fz: {min(values):+.3f} N")
        print(f"최대 Fz: {max(values):+.3f} N")

        return mean

    def run(self, execute=False):

        self.check_tcp()
        before = self.get_position()

        target = before.copy()
        target[0] += LINE_LENGTH

        print("\n[현재 TCP]")
        print(before)

        print("\n[목표 TCP]")
        print(target)

        print(f"\n목표: BASE +X {LINE_LENGTH:g}mm")
        print(f"속도: {DRAW_SPEED:g}mm/s")
        print("Z 높이 유지 / 펜 방향 유지")

        if not execute:
            print("\nDRY RUN - 이동 없음")
            return

        confirm = input(
            "\n종이 접촉 및 이동 경로 확인 후 DRAW 입력: "
        )

        if confirm != "DRAW":
            print("작업 취소")
            return

        fz_before = self.measure_fz("드로잉 전 Fz")

        req = MoveLine.Request()
        req.pos = [
            LINE_LENGTH, 0.0, 0.0,
            0.0, 0.0, 0.0
        ]
        req.vel = [DRAW_SPEED, 0.0]
        req.acc = [DRAW_ACC, 0.0]
        req.time = 0.0
        req.radius = 0.0
        req.ref = 0
        req.mode = 1
        req.blend_type = 0
        req.sync_type = 0

        print("\n드로잉 시작")

        result = self.call_service(
            self.move_client, req, timeout=60.0
        )

        if not result.success:
            raise RuntimeError("드로잉 이동 실패")

        after = self.get_position()
        fz_after = self.measure_fz("드로잉 후 Fz")

        print("\n=== 결과 ===")
        print(f"X 이동량: {after[0]-before[0]:+.3f}mm")
        print(f"Y 이동량: {after[1]-before[1]:+.3f}mm")
        print(f"Z 이동량: {after[2]-before[2]:+.3f}mm")
        print(f"Fz 변화량: {fz_after-fz_before:+.3f}N")
        print("드로잉 완료 - 자동 펜 이탈 없음")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--execute",
        action="store_true"
    )

    args = parser.parse_args()

    rclpy.init()
    node = DrawLine()

    try:
        node.run(execute=args.execute)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
