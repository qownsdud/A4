"""제공된 run_robot_drawing 본문을 모의 SDK로 실행해 UI 제어 분기를 검증합니다."""

import json
import os
import sys
import threading
from types import ModuleType
import pytest
from robot_worker_fixture import FakeApi
from test_live_control import wait
from art_artwork_pipeline import draw_image_standalone as script
from art_artwork_pipeline import live_control


@pytest.mark.parametrize('interruption',['PAUSE','STOP','FORCE','RESTART'])
def test_provided_robot_run_handles_pipe_pause_resume(monkeypatch,tmp_path,interruption):
    import rclpy

    if os.environ.get("ROS_DOMAIN_ID") != "99":
        pytest.skip("격리 도메인 99가 필요합니다.")
    import hashlib
    monkeypatch.setenv('ART_RECOVERY_DB',str(tmp_path/'recovery.sqlite3'))
    for key in ('STICK_FILE','PENS_FILE','CALIBRATION_FILE'):
        path=tmp_path/(key+'.json');path.write_text('{}')
        monkeypatch.setattr(script,key,path)
    plan_path=tmp_path/'drawing_plan.json';plan_path.write_text('{"immutable":true}')
    plan_hash=hashlib.sha256(plan_path.read_bytes()).hexdigest()
    holder = {}
    events = []
    original = live_control.LiveControl

    class Control(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, emit=events.append)
            holder["control"] = self

    class Api(FakeApi):
        def __init__(self, *args, **kwargs):
            super().__init__()
            if holder.get('restart_pose'):
                self.current=list(holder['restart_pose']);self.target=self.current[:]
            holder["api"] = self

    monkeypatch.setattr(live_control, "LiveControl", Control)
    monkeypatch.setattr(live_control, "DsrMotionApi", Api)
    init = ModuleType("DR_init")
    sdk = ModuleType("DSR_ROBOT2")
    common = ModuleType("DR_common2")
    for name in (
        "set_tool",
        "set_tcp",
        "movej",
        "movel",
        "movesx",
        "set_digital_output",
    ):
        setattr(sdk, name, lambda *a, **kw: 0)
    sdk.get_tool = lambda: script.TOOL_NAME
    sdk.get_tcp = lambda: script.TCP_NAME
    sdk.get_current_posx = lambda *a: (holder["api"].pose(), 0)
    sdk.get_tool_force = lambda *a: [0.0] * 6
    for name in ("DR_MV_MOD_ABS", "DR_BASE", "DR_MVS_VEL_CONST"):
        setattr(sdk, name, 0)
    sdk.DR_MV_MOD_REL = 1
    common.posx = lambda v: list(v)
    common.posj = lambda v: list(v)
    monkeypatch.setitem(sys.modules, "DR_init", init)
    monkeypatch.setitem(sys.modules, "DSR_ROBOT2", sdk)
    monkeypatch.setitem(sys.modules, "DR_common2", common)
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd)
    writer = os.fdopen(write_fd, "w", buffering=1)
    monkeypatch.setattr(sys, "stdin", reader)
    records = [
        dict(stroke_id=1,pen_id="PEN_2", layer="artwork", points_robot=[[0.0, 0.0], [10.0, 0.0]]),
        dict(
            stroke_id=2,pen_id="PEN_1",
            layer="calligraphy",
            points_robot=[[10.0, 10.0], [100.0, 10.0]],
        ),
    ]
    errors = []

    def run(checkpoint=None):
        try:
            script.run_robot_drawing(
                [[], [], []],
                [0.0, 0.0, 10.0, 0.0, 0.0, 0.0],
                [[0.0, 0.0, 10.0, 0.0, 0.0, 0.0]] * 3,
                [[x,y,0.,0.,0.,0.] for x in (-20.,50.,120.) for y in (-20.,50.,120.)],
                0.0,
                0.0,
                virtual=True,
                ordered_strokes=records,
                ui_job_id="PROVIDED",plan_path=plan_path,plan_sha256=plan_hash,resume_checkpoint=checkpoint,
                control_settings=dict(
                    force_limits=[10.0] * 6,
                    force_bias=[0.0] * 6,
                    motion_timeout=4.0,
                    position_tolerance=0.1,
                    joint_tolerance=0.1,
                ),
            )
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()

    def send(command, key):
        writer.write(
            json.dumps(dict(job_id="PROVIDED", command=command, request_id=key)) + "\n"
        )
        writer.flush()

    try:
        wait(lambda: "api" in holder, 15)
        wait(
            lambda: holder["control"].state == "DRAWING"
            and holder["control"].completed == 1
            and holder["api"].current[2] == 13.5
            and holder["api"].current[0] > 10,
            20,
        )
        if interruption in ('FORCE','RESTART'):
            holder['api'].forced=True
            wait(lambda:holder['control'].state=='FORCE_STOPPED')
        else:
            send(interruption,'P')
            wait(lambda:holder['control'].state=='PAUSED')
        if interruption=='PAUSE':assert holder['api'].joints()==script.HOME_JOINTS
        checkpoint=holder['control'].journal.store.latest()
        assert checkpoint['payload']['waypoint']['stroke_id']==2
        assert checkpoint['payload']['target_pose'][:2]==[10.,10.]
        assert checkpoint['payload']['resumable']
        start=len(holder['api'].commands)
        holder['api'].forced=False
        if interruption=='RESTART':
            # 이전 프로세스에 해당하는 제어 객체를 종료하고 DB만으로 새 실행을 엽니다.
            from art_artwork_pipeline.recovery_store import CheckpointStore
            holder['restart_pose']=holder['api'].pose()
            holder['control'].closed=True
            writer.close();worker.join(5)
            assert not worker.is_alive()
            reader.close()
            checkpoint=CheckpointStore().latest(job_id='PROVIDED')
            read_fd,write_fd=os.pipe();reader=os.fdopen(read_fd);writer=os.fdopen(write_fd,'w',buffering=1)
            monkeypatch.setattr(sys,'stdin',reader)
            worker=threading.Thread(target=run,args=(checkpoint,));worker.start()
            wait(lambda:holder['control'].state!='STOPPED',15)
            start=0
        else:
            send("RESUME", "R")
        wait(lambda: holder["control"].state == "COMPLETED", 20)
        assert not errors and holder["control"].completed == 2
        assert holder['control'].run_id==1
        assert hashlib.sha256(plan_path.read_bytes()).hexdigest()==plan_hash
        contacts=[p for p,j in holder['api'].commands[start:] if p[1]==10. and p[2]==13.5]
        assert contacts[0][:2]==[10.,10.] and any(p[:2]==[100.,10.] for p in contacts)
        assert holder['control'].journal.store.latest() is None
        assert [e["current_pen"] for e in events if e["completed_strokes"] == 1][
            0
        ] == "PEN_2"
        send("SHUTDOWN", "EXIT")
        worker.join(5)
        assert not worker.is_alive()
    finally:
        if worker.is_alive():
            holder["control"].closed = True
            worker.join(5)
        writer.close()
        reader.close()
        if rclpy.ok():
            rclpy.shutdown()
