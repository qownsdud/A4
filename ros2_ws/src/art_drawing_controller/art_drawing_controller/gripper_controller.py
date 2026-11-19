"""참고 코드의 DO1·DO2 순서를 유지하고 실제 개폐 입력 확인을 추가합니다."""

import time


class GripperController:
    def __init__(self, adapter):
        self.adapter = adapter

    def command(self, grip, runner):
        settings = self.adapter.settings["gripper"]
        # I/O 변경은 모션 게이트가 열렸을 때만 직렬화합니다.
        while True:
            runner.wait_running()
            with runner.session.condition:
                if runner.session.state != "RUNNING":
                    continue
                self.adapter.set_output(settings["grip_output"], 0)
                self.adapter.set_output(settings["release_output"], 0)
                self.adapter.set_output(
                    settings["grip_output"] if grip else settings["release_output"], 1
                )
                break
        wanted = "grip_input" if grip else "release_input"
        opposite = "release_input" if grip else "grip_input"
        if settings.get(wanted) is None or settings.get(opposite) is None:
            time.sleep(0.5)
            return
        deadline = time.monotonic() + 3.0
        confirmed = 0
        while time.monotonic() < deadline:
            runner.check_cancel()
            if (
                self.adapter.read_input(settings[wanted]) == 1
                and self.adapter.read_input(settings[opposite]) == 0
            ):
                confirmed += 1
                if confirmed >= 3:
                    return
            else:
                confirmed = 0
            time.sleep(0.03)
        raise RuntimeError("RG2 실제 개폐 상태 확인 시간 초과")

    def grip(self, runner):
        self.command(True, runner)

    def release(self, runner):
        self.command(False, runner)

    def off(self, runner):
        settings = self.adapter.settings["gripper"]
        while True:
            runner.wait_running()
            with runner.session.condition:
                if runner.session.state != "RUNNING":
                    continue
                self.adapter.set_output(settings["grip_output"], 0)
                self.adapter.set_output(settings["release_output"], 0)
                break
        time.sleep(0.5)

    def read_state(self):
        io = self.adapter.settings["gripper"]
        if io.get("grip_input") is None or io.get("release_input") is None:
            return dict(gripped=None, released=None)
        return dict(
            gripped=self.adapter.read_input(io["grip_input"]) == 1,
            released=self.adapter.read_input(io["release_input"]) == 1,
        )
