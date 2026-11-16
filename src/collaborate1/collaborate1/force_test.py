
import time
import statistics

import rclpy
from rclpy.node import Node
from dsr_msgs2.srv import GetToolForce


SERVICE_NAME = (
    "/dsr01/dsr_controller2/"
    "aux_control/get_tool_force"
)

SAMPLE_COUNT = 10
SAMPLE_INTERVAL = 0.2


class ForceTest(Node):

    def __init__(self):
        super().__init__("force_test")

        self.force_client = self.create_client(
            GetToolForce,
            SERVICE_NAME
        )

    def get_force(self):

        if not self.force_client.wait_for_service(
            timeout_sec=5.0
        ):
            raise RuntimeError("Fz 서비스 연결 실패")

        request = GetToolForce.Request()
        request.ref = 0  # BASE

        future = self.force_client.call_async(request)

        rclpy.spin_until_future_complete(
            self,
            future,
            timeout_sec=3.0
        )

        if not future.done():
            raise TimeoutError("Fz 측정 응답 시간 초과")

        result = future.result()

        if result is None or not result.success:
            raise RuntimeError("Fz 측정 실패")

        return float(result.tool_force[2])

    def run(self):

        print("\n=== Fz 측정 시작 ===")
        print("로봇 이동 없음")
        print(f"측정 횟수: {SAMPLE_COUNT}회\n")

        samples = []

        for i in range(SAMPLE_COUNT):

            fz = self.get_force()
            samples.append(fz)

            print(
                f"[{i+1:02d}/{SAMPLE_COUNT}] "
                f"Fz = {fz:+.3f} N",
                flush=True
            )

            if i < SAMPLE_COUNT - 1:
                time.sleep(SAMPLE_INTERVAL)

        print("\n=== 측정 결과 ===")
        print(f"평균 Fz: {statistics.mean(samples):+.3f} N")
        print(f"최소 Fz: {min(samples):+.3f} N")
        print(f"최대 Fz: {max(samples):+.3f} N")
        print(f"표준편차: {statistics.stdev(samples):.3f} N")
        print("\n측정 완료")


def main():

    rclpy.init()

    node = ForceTest()

    try:
        node.run()

    except Exception as e:
        print(f"오류 발생: {e}")

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
