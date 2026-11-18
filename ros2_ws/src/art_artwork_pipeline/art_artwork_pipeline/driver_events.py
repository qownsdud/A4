"""제어기 알람을 기억합니다. 정상 상태 복귀만으로 사건을 지우지 않습니다."""

import threading


class DriverAlarmLatch:
    def __init__(self):
        self.lock = threading.Lock()
        self.generation = 0
        self.reason = ''

    def receive(self, message):
        # 일반 안내는 무시하고 오류 및 안전 경고는 원인 추측 없이 정지 대상으로 취급합니다.
        if message.level < 3 and not (message.group == 5 and message.level >= 2):
            return
        with self.lock:
            self.generation += 1
            self.reason = (f'제어기 알람 level={message.level}, group={message.group}, '
                           f'code={message.code}: {message.msg1} {message.msg2} {message.msg3}')[:500]

    def snapshot(self):
        with self.lock:
            return self.generation, self.reason

    def acknowledge(self, generation):
        with self.lock:
            if self.generation != generation:
                raise RuntimeError('복구 확인 중 새 제어기 알람이 발생했습니다.')
            self.reason = ''


class DriverEventMonitor:
    def __init__(self, context, robot_id):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from dsr_msgs2.msg import RobotError
        self.latch = DriverAlarmLatch()
        self.node = rclpy.create_node('a4_driver_alarm_monitor', namespace=robot_id, context=context)
        self.topic = f'/{robot_id}/error'
        self.subscription = self.node.create_subscription(RobotError, self.topic, self.latch.receive, 100)
        self.executor = SingleThreadedExecutor(context=context)
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()

    def ensure_ready(self, timeout=3.0):
        import time
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.node.count_publishers(self.topic) == 1:
                return
            time.sleep(.05)
        raise RuntimeError('제어기 알람 발행자를 하나로 확인할 수 없습니다: ' + self.topic)

    def close(self):
        self.executor.shutdown(timeout_sec=2)
        self.thread.join(2)
        self.node.destroy_node()
