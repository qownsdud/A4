
#!/usr/bin/env python3
"""Doosan M0609: 여러 좌표 경로 드로잉 테스트."""

import argparse
import math
import rclpy

from rclpy.node import Node
from dsr_msgs2.srv import (
    GetCurrentTcp,
    GetCurrentPosx,
    GetToolForce,
    MoveLine,
)

PREFIX = "/dsr01/dsr_controller2"

# ===== 기본 설정 =====
DRAW_SPEED = 8.0
DRAW_ACC = 15.0
LIFT_HEIGHT = 5.0

# 앞선 실험에서 확인한 -93mm 접촉 좌표
CONTACT_Z = 297.173
Z_TOLERANCE = 0.7

# ===== 그림 데이터 =====
# 각 경로의 좌표는 시작점 기준 상대 XY (mm)
# 한 경로 안에서는 붓을 들지 않음
# 경로 사이에서는 붓을 들어 이동
PATHS = [
    [(0, 0), (20, 0), (20, 20)],
    [(0, 20), (20, 0)],
]


class DrawPath(Node):

    def __init__(self):
        super().__init__("draw_path")

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
            raise RuntimeError(
                f"TCP 불일치: {result.info!r}"
            )

        print("TCP 확인:", result.info)

    def get_position(self):
        req = GetCurrentPosx.Request()
        req.ref = 0

        result = self.call_service(self.pos_client, req)

        if not result.success:
            raise RuntimeError("TCP 좌표 조회 실패")

        return list(result.task_pos_info[0].data[:6])

    def get_fz(self):
        req = GetToolForce.Request()
        req.ref = 0

        result = self.call_service(
            self.force_client, req, timeout=5.0
        )

        if not result.success:
            raise RuntimeError("Fz 조회 실패")

        fz = float(result.tool_force[2])

        if not math.isfinite(fz):
            raise RuntimeError("유효하지 않은 Fz")

        return fz

    def move_relative(self, x, y, z):
        before = self.get_position()

        req = MoveLine.Request()
        req.pos = [
            float(x), float(y), float(z),
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

        result = self.call_service(
            self.move_client, req, timeout=60.0
        )

        if not result.success:
            raise RuntimeError("로봇 이동 실패")

        after = self.get_position()
        expected = [
            before[0] + x,
            before[1] + y,
            before[2] + z,
        ]

        error = math.dist(after[:3], expected)

        print(
            f"  실제 TCP: "
            f"X={after[0]:.3f} "
            f"Y={after[1]:.3f} "
            f"Z={after[2]:.3f}"
        )
        print(f"  위치 오차: {error:.3f}mm")

        if error > 1.0:
            raise RuntimeError(
                "예상 위치와 차이가 큽니다. 작업 중단"
            )

        return after

    def print_preview(self, start):
        print("\n===== 예상 그림 경로 =====")

        for path_no, path in enumerate(PATHS, start=1):
            print(f"\n경로 {path_no}")

            for x, y in path:
                print(
                    f"  X={start[0]+x:.3f}, "
                    f"Y={start[1]+y:.3f}, "
                    f"Z={start[2]:.3f}"
                )

        print("\n그림 영역: 20 x 20mm")
        print(f"경로 간 붓 상승 높이: {LIFT_HEIGHT}mm")

    def run(self, execute=False, mode="air"):
        print("\n===== 좌표 기반 드로잉 =====")

        self.check_tcp()
        start = self.get_position()

        print("\n시작 TCP:", start)
        print("실행 모드:", mode)

        self.print_preview(start)

        if not execute:
            print("\nDRY RUN 완료 - 이동 없음")
            return

        if mode == "draw":
            if abs(start[2] - CONTACT_Z) > Z_TOLERANCE:
                raise RuntimeError(
                    "접촉 높이가 아닙니다. "
                    "현재 Z 좌표를 확인하세요."
                )
        else:
            if start[2] < CONTACT_Z + LIFT_HEIGHT - 0.7:
                raise RuntimeError(
                    "공중 테스트를 위한 높이가 부족합니다."
                )

        print("\n주의: 실제 로봇 이동을 실행합니다.")
        print("20x20mm 경로와 펜 상승 공간을 확인하세요.")
        print("실시간 힘 제어 및 자동 정지 기능은 없습니다.")

        confirm = input("\n확인 후 DRAW 입력: ")

        if confirm != "DRAW":
            print("작업 취소")
            return

        # 현재 위치를 그림의 (0, 0)으로 사용
        current_x = 0.0
        current_y = 0.0

        print(f"\n시작 Fz: {self.get_fz():+.3f} N")

        for path_no, path in enumerate(PATHS, start=1):

            print(f"\n===== 경로 {path_no} =====")

            first_x, first_y = path[0]

            if path_no > 1:
                # 이전 경로의 끝에서 펜 들어 올리기
                print("펜 들어 올리기")
                self.move_relative(
                    0, 0, LIFT_HEIGHT
                )

                # 공중에서 다음 경로 시작점 이동
                dx = first_x - current_x
                dy = first_y - current_y

                print(
                    f"다음 시작점 이동: "
                    f"X {dx:+g}, Y {dy:+g}"
                )
                self.move_relative(dx, dy, 0)

                # 원래 그리기 높이로 내리기
                print("펜 내리기")
                self.move_relative(
                    0, 0, -LIFT_HEIGHT
                )

                current_x = first_x
                current_y = first_y

            print(
                f"경로 시작 Fz: "
                f"{self.get_fz():+.3f} N"
            )

            for point_no, (x, y) in enumerate(
                path[1:], start=1
            ):
                dx = x - current_x
                dy = y - current_y

                print(
                    f"\n선 {point_no}: "
                    f"X {dx:+g}mm, Y {dy:+g}mm"
                )

                self.move_relative(dx, dy, 0)

                current_x = x
                current_y = y

                print(
                    f"이동 후 Fz: "
                    f"{self.get_fz():+.3f} N"
                )

        # 모든 경로 정상 완료 후 펜 상승
        print("\n모든 경로 완료")
        print("펜 들어 올리기")

        self.move_relative(0, 0, LIFT_HEIGHT)

        print("\n===== 최종 결과 =====")
        print("최종 TCP:", self.get_position())
        print("드로잉 완료")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--execute",
        action="store_true"
    )
    parser.add_argument(
        "--mode",
        choices=["air", "draw"],
        default="air"
    )

    args = parser.parse_args()

    rclpy.init()
    node = DrawPath()

    try:
        node.run(
            execute=args.execute,
            mode=args.mode
        )
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
