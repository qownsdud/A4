
#!/usr/bin/env python3
"""Doosan M0609 힘 제어 사전 진단.

- 현재 TCP 및 위치 확인
- Fz 연속 측정
- 힘 제어 관련 ROS2 서비스 확인
- 서비스 Request 필드 확인

로봇 이동 없음.
컴플라이언스 및 힘 제어 활성화 없음.
"""

import argparse
import math
import statistics
import time

import rclpy
from rclpy.node import Node

from dsr_msgs2.srv import (
    GetCurrentTcp,
    GetCurrentPosx,
    GetToolForce,
    TaskComplianceCtrl,
    SetDesiredForce,
    ReleaseForce,
    ReleaseComplianceCtrl,
)

PREFIX = "/dsr01/dsr_controller2"

# 이전에 확인한 접촉 위치 (참고값)
CONTACT_Z = 297.173

SAMPLE_COUNT = 20
SAMPLE_INTERVAL = 0.2

SERVICES = {
    "TCP 조회": (
        GetCurrentTcp,
        f"{PREFIX}/tcp/get_current_tcp"
    ),
    "TCP 위치 조회": (
        GetCurrentPosx,
        f"{PREFIX}/aux_control/get_current_posx"
    ),
    "외력 조회": (
        GetToolForce,
        f"{PREFIX}/aux_control/get_tool_force"
    ),
    "컴플라이언스 활성화": (
        TaskComplianceCtrl,
        f"{PREFIX}/force/task_compliance_ctrl"
    ),
    "목표 힘 설정": (
        SetDesiredForce,
        f"{PREFIX}/force/set_desired_force"
    ),
    "힘 제어 해제": (
        ReleaseForce,
        f"{PREFIX}/force/release_force"
    ),
    "컴플라이언스 해제": (
        ReleaseComplianceCtrl,
        f"{PREFIX}/force/release_compliance_ctrl"
    ),
}


class ForceControlTest(Node):

    def __init__(self):
        super().__init__("force_control_test")

        self.service_clients = {}

        for name, (srv_type, srv_name) in SERVICES.items():
            self.service_clients[name] = self.create_client(
                srv_type, srv_name
            )

    def call(self, name, request):
        client = self.service_clients[name]

        if not client.wait_for_service(timeout_sec=3.0):
            raise RuntimeError(
                f"서비스 연결 실패: {name}"
            )

        future = client.call_async(request)

        rclpy.spin_until_future_complete(
            self,
            future,
            timeout_sec=5.0
        )

        if not future.done():
            raise TimeoutError(
                f"서비스 응답 시간 초과: {name}"
            )

        result = future.result()

        if result is None or not result.success:
            raise RuntimeError(
                f"서비스 응답 실패: {name}"
            )

        return result

    def check_services(self):
        print("\n===== 서비스 확인 =====")

        for name, client in self.service_clients.items():
            connected = client.wait_for_service(
                timeout_sec=2.0
            )

            status = "OK" if connected else "NOT FOUND"
            print(f"{name}: {status}")

            if not connected:
                raise RuntimeError(
                    f"필요한 서비스가 없습니다: {name}"
                )

    def inspect_interfaces(self):
        print("\n===== 힘 제어 서비스 인터페이스 =====")

        names = [
            "컴플라이언스 활성화",
            "목표 힘 설정",
            "힘 제어 해제",
            "컴플라이언스 해제",
        ]

        for name in names:
            srv_type, _ = SERVICES[name]

            print(f"\n[{name}]")

            fields = (
                srv_type.Request
                .get_fields_and_field_types()
            )

            if not fields:
                print("  요청 필드 없음")
                continue

            for field, field_type in fields.items():
                print(f"  {field}: {field_type}")

    def get_tcp(self):
        result = self.call(
            "TCP 조회",
            GetCurrentTcp.Request()
        )

        return result.info

    def get_position(self):
        req = GetCurrentPosx.Request()
        req.ref = 0

        result = self.call(
            "TCP 위치 조회", req
        )

        return list(
            result.task_pos_info[0].data[:6]
        )

    def get_fz(self):
        req = GetToolForce.Request()
        req.ref = 0

        result = self.call(
            "외력 조회", req
        )

        fz = float(result.tool_force[2])

        if not math.isfinite(fz):
            raise RuntimeError(
                "Fz 값이 유효하지 않습니다"
            )

        return fz

    def measure_force(self):
        print("\n===== Fz 연속 측정 =====")

        samples = []

        for i in range(SAMPLE_COUNT):
            fz = self.get_fz()
            samples.append(fz)

            print(
                f"[{i+1:02d}/{SAMPLE_COUNT}] "
                f"Fz = {fz:+.3f} N",
                flush=True
            )

            if i < SAMPLE_COUNT - 1:
                time.sleep(SAMPLE_INTERVAL)

        print("\n===== Fz 측정 결과 =====")
        print(
            f"평균: "
            f"{statistics.mean(samples):+.3f} N"
        )
        print(
            f"최소: {min(samples):+.3f} N"
        )
        print(
            f"최대: {max(samples):+.3f} N"
        )
        print(
            f"표준편차: "
            f"{statistics.stdev(samples):.3f} N"
        )

    def run(self):
        print("\n===== M0609 힘 제어 사전 테스트 =====")
        print("로봇 이동: 없음")
        print("힘 제어 활성화: 없음")

        self.check_services()
        self.inspect_interfaces()

        tcp = self.get_tcp()
        print(f"\n현재 TCP: {tcp!r}")

        if tcp != "PenGripper":
            raise RuntimeError(
                "PenGripper TCP가 아닙니다"
            )

        pos = self.get_position()

        print("\n===== 현재 TCP 위치 =====")
        print(f"X: {pos[0]:.3f} mm")
        print(f"Y: {pos[1]:.3f} mm")
        print(f"Z: {pos[2]:.3f} mm")
        print(
            f"기존 접촉 Z와 차이: "
            f"{pos[2]-CONTACT_Z:+.3f} mm"
        )

        self.measure_force()

        end_pos = self.get_position()

        displacement = math.dist(
            pos[:3],
            end_pos[:3]
        )

        print("\n===== 최종 상태 =====")
        print(
            f"측정 전후 TCP 위치 차이: "
            f"{displacement:.3f} mm"
        )
        print("힘 제어 명령 전송 없음")
        print("진단 완료")


def main():
    parser = argparse.ArgumentParser()

    parser.parse_args()

    rclpy.init()
    node = ForceControlTest()

    try:
        node.run()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
