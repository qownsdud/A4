
#!/usr/bin/env python3
"""공중/접촉 Fz 비교 테스트 - 로봇 이동 및 힘 제어 없음."""

import argparse
import json
import math
import statistics
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from dsr_msgs2.srv import (
    GetCurrentTcp,
    GetCurrentPosx,
    GetToolForce,
)

PREFIX = "/dsr01/dsr_controller2"
BASELINE_FILE = Path.home() / "force_compare_air.json"

SAMPLE_COUNT = 20
INTERVAL = 0.2


class ForceCompare(Node):

    def __init__(self):
        super().__init__("force_compare")

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

    def call(self, client, request):
        if not client.wait_for_service(timeout_sec=5.0):
            raise RuntimeError("서비스 연결 실패")

        future = client.call_async(request)

        rclpy.spin_until_future_complete(
            self, future, timeout_sec=5.0
        )

        if not future.done():
            raise TimeoutError("서비스 응답 시간 초과")

        result = future.result()

        if result is None or not result.success:
            raise RuntimeError("서비스 호출 실패")

        return result

    def get_tcp(self):
        result = self.call(
            self.tcp_client,
            GetCurrentTcp.Request()
        )
        return result.info

    def get_pos(self):
        req = GetCurrentPosx.Request()
        req.ref = 0

        result = self.call(self.pos_client, req)
        return list(result.task_pos_info[0].data[:6])

    def get_force(self):
        req = GetToolForce.Request()
        req.ref = 0

        result = self.call(self.force_client, req)
        values = [float(v) for v in result.tool_force]

        if not all(math.isfinite(v) for v in values):
            raise RuntimeError("유효하지 않은 외력값")

        return values

    def measure(self):
        samples = []

        for i in range(SAMPLE_COUNT):
            fz = self.get_force()[2]
            samples.append(fz)

            print(
                f"[{i+1:02d}/{SAMPLE_COUNT}] "
                f"Fz = {fz:+.3f} N",
                flush=True
            )

            if i < SAMPLE_COUNT - 1:
                time.sleep(INTERVAL)

        return {
            "mean": statistics.mean(samples),
            "minimum": min(samples),
            "maximum": max(samples),
            "stddev": statistics.stdev(samples),
        }

    def run(self, phase):
        print(f"\n===== {phase.upper()} 측정 =====")
        print("로봇 이동 없음 / 힘 제어 없음")

        tcp = self.get_tcp()
        if tcp != "PenGripper":
            raise RuntimeError(f"TCP 불일치: {tcp!r}")

        before = self.get_pos()
        print("현재 TCP:", before)

        if phase == "contact":
            if not BASELINE_FILE.exists():
                raise RuntimeError(
                    "공중 기준값이 없습니다. "
                    "먼저 --phase air 실행"
                )

            air = json.loads(
                BASELINE_FILE.read_text(encoding="utf-8")
            )

            air_pos = air["position"]
            xy_error = math.dist(before[:2], air_pos[:2])
            z_drop = air_pos[2] - before[2]

            print(f"공중 대비 XY 차이: {xy_error:.3f}mm")
            print(f"공중 대비 Z 하강: {z_drop:.3f}mm")

            if xy_error > 0.5:
                raise RuntimeError(
                    "공중 측정 위치와 XY가 다릅니다"
                )

            if not 2.0 <= z_drop <= 10.0:
                raise RuntimeError(
                    "공중/접촉 높이 차이가 예상 범위를 "
                    "벗어났습니다"
                )

        result = self.measure()

        after = self.get_pos()
        drift = math.dist(before[:3], after[:3])

        if drift > 0.5:
            raise RuntimeError(
                f"측정 중 TCP 이동 감지: {drift:.3f}mm"
            )

        print("\n===== 결과 =====")
        print(f"평균: {result['mean']:+.3f} N")
        print(f"최소: {result['minimum']:+.3f} N")
        print(f"최대: {result['maximum']:+.3f} N")
        print(f"표준편차: {result['stddev']:.3f} N")

        if phase == "air":
            data = {
                "position": before,
                "measurement": result,
            }

            BASELINE_FILE.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8"
            )

            print(f"\n공중 기준 저장: {BASELINE_FILE}")
            print("다음: 같은 XY 위치에서 접촉 상태 측정")

        else:
            air_mean = air["measurement"]["mean"]
            contact_mean = result["mean"]
            delta = contact_mean - air_mean

            print("\n===== 공중/접촉 비교 =====")
            print(f"공중 Fz: {air_mean:+.3f} N")
            print(f"접촉 Fz: {contact_mean:+.3f} N")
            print(f"변화량: {delta:+.3f} N")
            print(
                "\n주의: 이 변화량은 접촉 반력의 "
                "추정 단서이며, 순수 필압은 아닙니다."
            )

        print("\n측정 완료")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--phase",
        choices=["air", "contact"],
        required=True
    )

    args = parser.parse_args()

    rclpy.init()
    node = ForceCompare()

    try:
        node.run(args.phase)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
