"""검증 전용 모션 관측기·IPC 작업자. 실제 로봇 API를 호출하지 않습니다."""

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from art_artwork_pipeline.live_control import (
    LiveControl,
    length,
    load_settings,
    ResumeDrawing,
    ForceStopped,
    WorkerExit,
    CancelDrawing,
)


class FakeApi:
    def __init__(self):
        self.current = [0.0, 0.0, 20.0, 0.0, 0.0, 0.0]
        self.target = self.current[:]
        self.start = self.current[:]
        self.steps = 0
        self.home = [0.0, 0.0, 100.0, 0.0, 0.0, 0.0]
        self.commands = []
        self.forced = False
        self.stops = 0

    def start_monitor(self, robot_id):
        # 제공된 실제 함수의 시험에서 장비 대신 시험 관측기를 사용합니다.
        pass

    def state(self):
        return 1

    def pose(self):
        return self.current[:]

    def joints(self):
        return self.current[:]

    def ready(self):
        if (
            self.forced
            or os.environ.get("A4_TEST_FORCE_FLAG")
            and Path(os.environ["A4_TEST_FORCE_FLAG"]).exists()
        ):
            raise RuntimeError("외력 해소 필요")

    def force(self):
        flag = (
            self.forced
            or os.environ.get("A4_TEST_FORCE_FLAG")
            and Path(os.environ["A4_TEST_FORCE_FLAG"]).exists()
        )
        return [20.0 if flag else 0.0] + [0.0] * 5

    def stop(self):
        self.stops += 1
        self.target = self.current[:]

    def begin(self, target, joint, vel, acc):
        self.start = self.current[:]
        self.target = list(target)
        self.steps = 0
        self.commands.append((list(target), joint))

    def finished(self, target, joint):
        if self.current == list(target):
            return True
        gate=os.environ.get('A4_TEST_MOTION_GATE')
        if gate and Path(gate).exists() and not joint and self.current[2]==0 and target[2]==0 and self.steps>=2:
            return False
        self.steps += 1
        fraction = min(1.0, self.steps / 5)
        self.current = [a + (b - a) * fraction for a, b in zip(self.start, self.target)]
        return fraction == 1.0


def execute(control, api, strokes):
    """실제 제어 로직에 가짜 관측기만 연결하며, 복구점은 실제 저장소를 사용합니다."""
    import tempfile
    from art_artwork_pipeline.recovery_store import RecoveryJournal, CheckpointStore
    if control.journal is None:
        control.attach_journal(RecoveryJournal(control.job_id, '/test/plan.json', 'TEST',
            store=CheckpointStore(Path(tempfile.mkdtemp())/'recovery.sqlite3')))
    control.runtime=dict(held_pen_id=None,phase='drawing')
    pending=None
    try:
        control.begin_run()
        while True:
            try:
                start_record=0;start_point=1
                if pending:
                    cursor=pending['payload']['waypoint']
                    start_record=next(i for i,r in enumerate(strokes) if int(r.get('stroke_id',i+1))==cursor['stroke_id'])
                    start_point=cursor['point_index']
                    control.recovery_move(pending);pending=None
                for record_index,record in enumerate(strokes):
                    if record_index<start_record:continue
                    points=record['points_mm']
                    control.pen=record.get('pen_id','PEN_1')
                    control.runtime.update(held_pen_id=control.pen,phase='drawing')
                    offset=start_point if record_index==start_record else 1
                    if offset==1 and not control.waypoint:
                        control.motion([*points[0],0.,0.,0.,0.])
                    elif record_index!=start_record or start_point==1:
                        control.motion([*points[0],0.,0.,0.,0.])
                    for index in range(offset,len(points)):
                        control.draw_line([*points[index],0.,0.,0.,0.],25.,25.,
                            planned_start=[*points[index-1],0.,0.,0.,0.],
                            stroke_id=record.get('stroke_id',record_index+1),point_index=index)
                    control.completed+=1;control.emit()
                control.motion(api.home,joint=True)
                control.complete()
            except ResumeDrawing as exc:
                pending=exc.checkpoint
            except ForceStopped as exc:
                try:control.wait_force_reset(exc)
                except ResumeDrawing as recovery:pending=recovery.checkpoint
    except (WorkerExit,CancelDrawing):
        api.stop();control.emit('STOPPED','시험 이동 정지 확인')
    except Exception as exc:
        control.emit('RECOVERY_REQUIRED',str(exc),'TEST_FAILURE')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--job-id")
    args, _ = parser.parse_known_args()
    data = json.loads(Path(args.input).read_text())
    strokes = data["strokes"]
    api = FakeApi()
    control = LiveControl(
        args.job_id,
        sum(length(s["points_mm"]) for s in strokes),
        len(strokes),
        load_settings(),
    )
    control.bind(api, api.home, lambda current: max(current[2], 50.0))
    threading.Thread(
        target=control.read_commands, args=(sys.stdin,), daemon=True
    ).start()
    execute(control, api, strokes)


if __name__ == "__main__":
    main()
