"""draw_image_standalone의 pick_from_slot / return_to_slot 동작과 동일하게 슬롯 집기·반납을 실행합니다."""

from .gripper_controller import GripperController


class PenController:
    def __init__(self, adapter, runner=None):
        self.adapter, self.runner = adapter, runner
        self.gripper = GripperController(adapter)

    def _velocities(self):
        settings = self.adapter.settings
        l_vel = settings.get("travel_velocity", 80.0)
        l_acc = settings.get("travel_acceleration", settings.get("acceleration", 80.0))
        p_vel = settings.get("pick_velocity", 25.0)
        p_acc = settings.get("pick_acceleration", settings.get("acceleration", 25.0))
        return l_vel, l_acc, p_vel, p_acc

    def pick_from_slot(self, slot_pose):
        settings = self.adapter.settings
        l_vel, l_acc, p_vel, p_acc = self._velocities()
        approach = list(slot_pose)
        approach[2] += settings.get("slot_approach_mm", 100.0)
        self.gripper.release(self.runner)
        self.runner.move([approach], l_vel, l_acc)
        self.runner.move([list(slot_pose)], p_vel, p_acc)
        self.gripper.grip(self.runner)
        self.runner.move([approach], p_vel, p_acc)

    def return_to_slot(self, slot_pose, on_released=None):
        settings = self.adapter.settings
        l_vel, l_acc, p_vel, p_acc = self._velocities()
        approach = list(slot_pose)
        approach[2] += settings.get("slot_approach_mm", 100.0)
        self.runner.move([approach], l_vel, l_acc)
        self.runner.move([list(slot_pose)], p_vel, p_acc)
        self.gripper.release(self.runner)
        if on_released is not None:
            on_released()
        self.runner.move([approach], p_vel, p_acc)

    def select(self, pen_id):
        if pen_id not in ("PEN_1", "PEN_2", "PEN_3", "PEN_4"):
            raise ValueError("지원하지 않는 논리 펜입니다.")
        if pen_id not in self.adapter.settings["pen_slots"]:
            raise ValueError(f"펜 슬롯이 설정되지 않았습니다: {pen_id}")
        self.adapter.require_ready()
        if self.runner is None:
            raise RuntimeError("실행 모션 게이트가 필요합니다.")
        if self.adapter.held_pen == pen_id:
            return
        self.return_current()
        slot = self.adapter.settings["pen_slots"][pen_id]["pose"]
        self.pick_from_slot(slot)
        self.adapter.held_pen = pen_id

    def return_current(self):
        pen = self.adapter.held_pen
        if pen is None:
            return
        slot = self.adapter.settings["pen_slots"][pen]["pose"]
        self.return_to_slot(
            slot, on_released=lambda: setattr(self.adapter, "held_pen", None)
        )
