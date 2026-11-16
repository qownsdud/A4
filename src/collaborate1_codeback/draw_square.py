
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

# ===== 사용자 설정 =====
SQUARE_SIZE = 20.0   # 사각형 한 변 (mm)
LIFT_HEIGHT = 5.0    # 드로잉 완료 후 상승 높이 (mm)

DRAW_SPEED = 5.0     # mm/s
DRAW_ACC = 10.0      # mm/s²

# -93mm 접촉 실험에서 측정한 TCP Z 좌표
CONTACT_Z = 297.173
Z_TOLERANCE = 0.7

# 사각형 경로: X, Y, Z (상대 이동)
SQUARE_PATH = [
    [SQUARE_SIZE, 0.0, 0.0],
    [0.0, SQUARE_SIZE, 0.0],
    [-SQUARE_SIZE, 0.0, 0.0],
    [0.0, -SQUARE_SIZE, 0.0],
]


class DrawSquare(Node):

    def __init__(self):
        super().__init__("draw_square")

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
                "응답 시간 초과: 로봇 상태를 확인하세요"
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

        print("TCP 확인:", result.info)

    def get_position(self):

        req = GetCurrentPosx.Request()
        req.ref = 0

        result = self.call_service(self.pos_client, req)

        if not result.success:
            raise RuntimeError("현재 위치 조회 실패")

        return list(result.task_pos_info[0].data[:6])

    def get_fz(self):

        req = GetToolForce.Request()
        req.ref = 0

        result = self.call_service(
            self.force_client, req, timeout=5.0
        )

        if not result.success:
            raise RuntimeError("Fz 측정 실패")

        fz = float(result.tool_force[2])

        if not math.isfinite(fz):
            raise RuntimeError("유효하지 않은 Fz 값")

        return fz

    def move_relative(self, x, y, z):

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
            self.move_client,
            req,
            timeout=60.0
        )

        if not result.success:
            raise RuntimeError("로봇 이동 실패")

    def run(self, execute=False, mode="air"):

        print("\n===== 사각형 드로잉 테스트 =====")

        self.check_tcp()

        start = self.get_position()

        print("\n현재 TCP:", start)
        print(f"사각형 크기: {SQUARE_SIZE:g}mm")
        print(f"실행 모드: {mode}")

        # 예상 경로 표시
        x, y, z = start[:3]

        for i, (dx, dy, dz) in enumerate(
            SQUARE_PATH, start=1
        ):
            x += dx
            y += dy
            z += dz

            print(
                f"{i}번 경로: "
                f"X={x:.3f}, "
                f"Y={y:.3f}, "
                f"Z={z:.3f}"
            )

        if not execute:
            print("\nDRY RUN 완료 - 실제 이동 없음")
            return

        # 모드에 따른 시작 높이 검사
        if mode == "draw":
            if abs(start[2] - CONTACT_Z) > Z_TOLERANCE:
                raise RuntimeError(
                    "접촉 기준 Z 좌표와 불일치합니다. "
                    "현재 위치를 확인하세요."
                )
        else:
            if start[2] < CONTACT_Z + LIFT_HEIGHT:
                raise RuntimeError(
                    "공중 테스트 높이가 부족합니다."
                )

        print("\n주의: 사각형 경로 전체를 확인하세요.")
        print("이 코드는 실시간 힘 제어를 수행하지 않습니다.")

        confirmation = input(
            "작업 공간과 로봇 안전 상태 확인 후 DRAW 입력: "
        )

        if confirmation != "DRAW":
            print("작업 취소")
            return

        print("\n드로잉 전 Fz:", f"{self.get_fz():+.3f} N")

        # 4개 변 순서대로 실행
        for i, (dx, dy, dz) in enumerate(
            SQUARE_PATH, start=1
        ):
            print(f"\n[{i}/4] 경로 이동 시작")

            self.move_relative(dx, dy, dz)

            current = self.get_position()
            fz = self.get_fz()

            print("현재 TCP:", current)
            print(f"이동 후 Fz: {fz:+.3f} N")

        print("\n사각형 경로 완료")

        # 정상 완료 후에만 붓 들어 올리기
        print(f"붓 들어 올리기: Z +{LIFT_HEIGHT:g}mm")

        self.move_relative(
            0.0, 0.0, LIFT_HEIGHT
        )

        end = self.get_position()

        print("\n===== 최종 결과 =====")
        print("최종 TCP:", end)
        print("작업 완료")

        # 이동 중 오류가 발생하면 자동 재시도나
        # 추가 이동 없이 예외를 발생시킴


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 로봇 이동 허용"
    )

    parser.add_argument(
        "--mode",
        choices=["air", "draw"],
        default="air",
        help="air=공중 테스트, draw=접촉 드로잉"
    )

    args = parser.parse_args()

    rclpy.init()
    node = DrawSquare()

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
