"""생산 제어 세션의 중간 선분·홈 왕복·외력·초기화를 검증합니다."""

import threading
import time
import pytest
from art_artwork_pipeline.live_control import LiveControl, fraction_at, load_settings
from robot_worker_fixture import FakeApi, execute


def wait(predicate, seconds=8.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.003)
    raise AssertionError("관측 상태 대기 시간 초과")


def session():
    strokes = [
        dict(points_mm=[[0.0, 0.0], [10.0, 0.0]], pen_id="PEN_1"),
        dict(points_mm=[[10.0, 10.0], [100.0, 10.0]], pen_id="PEN_2"),
    ]
    events = []
    api = FakeApi()
    control = LiveControl(
        "TEST",
        100.0,
        2,
        dict(
            force_limits=[10.0] * 6,
            force_bias=[0.0] * 6,
            motion_timeout=3.0,
            position_tolerance=0.1,
            joint_tolerance=0.1,
        ),
        events.append,
    )
    control.bind(api, api.home, lambda current: max(50.0, current[2]))
    worker = threading.Thread(target=execute, args=(control, api, strokes))
    worker.start()
    return control, api, events, worker


def close(control, worker):
    control.closed = True
    worker.join(4)
    assert not worker.is_alive()


def test_length_weighting_and_completion():
    c, a, events, w = session()
    try:
        wait(lambda: c.state == "COMPLETED")
        assert c.done == 100.0 and c.completed == 2
        assert any(
            e["completed_strokes"] == 1 and e["completed_length_mm"] == 10.0
            for e in events
        )
    finally:
        close(c, w)


def test_pause_home_resume_exact_remaining_line():
    c, a, events, w = session()
    try:
        wait(
            lambda: a.current[1] == 10 and a.current[2] == 0 and 10 < a.current[0] < 100
        )
        c.request("PAUSE", "P")
        wait(lambda: c.state == "PAUSED")
        assert a.current == a.home and 10 < c.done < 100
        old = c.done
        start = len(a.commands)
        c.request("RESUME", "R")
        wait(lambda: c.state == "COMPLETED")
        contacts = [p for p, j in a.commands[start:] if p[1] == 10 and p[2] == 0]
        assert contacts[0][0] == 10 and any(p[0] == 100 for p in contacts)
        assert any(
            e["state"] == "PAUSED" and e["completed_length_mm"] == old for e in events
        )
    finally:
        close(c, w)


def test_force_resumes_saved_segment_without_starting_first_stroke():
    c,a,events,w=session()
    try:
        wait(lambda:a.current[1]==10 and a.current[2]==0 and 10<a.current[0]<100)
        a.forced=True
        wait(lambda:c.state=='FORCE_STOPPED')
        assert c.force_latched and a.stops>0
        c.request('RESUME','BLOCKED')
        wait(lambda:c.control_error=='RESUME_NOT_READY')
        assert c.run_id==1
        a.forced=False;start=len(a.commands)
        c.request('RESUME','RESUME')
        wait(lambda:c.state=='COMPLETED')
        assert c.run_id==1 and c.completed==2
        assert not any(p[:2]==[0.,0.] and p[2]==0 for p,j in a.commands[start:])
        assert c.journal.store.latest() is None
    finally:close(c,w)


def test_stop_preserves_waypoint_and_resume_keeps_run():
    c,a,events,w=session()
    try:
        wait(lambda:a.current[1]==10 and a.current[2]==0 and 10<a.current[0]<100)
        c.request('STOP','STOP')
        wait(lambda:c.state=='PAUSED')
        assert c.current_checkpoint['payload']['target_pose'][:2]==[10.,10.]
        assert c.completed==1
        c.request('RESUME','RESUME')
        wait(lambda:c.state=='COMPLETED')
        assert c.run_id==1 and c.completed==2
    finally:close(c,w)


def test_changed_home_refuses_resume():
    c, a, events, w = session()
    try:
        wait(lambda: a.current[2] == 0 and a.current[0] > 1)
        c.request("PAUSE", "P")
        wait(lambda: c.state == "PAUSED")
        a.current[0] += 10
        c.request("RESUME", "R")
        wait(lambda: c.state == "RECOVERY_REQUIRED")
        assert c.completed < 2
    finally:
        close(c, w)


def test_settings_and_off_path_refused(tmp_path):
    import json

    path = tmp_path / "settings.json"
    path.write_text(json.dumps(dict(validated=False)))
    with pytest.raises(ValueError):
        load_settings(path)
    assert fraction_at([5, 0, 0], [0, 0, 0], [10, 0, 0], 0.1) == 0.5
    with pytest.raises(RuntimeError):
        fraction_at([5, 2, 0], [0, 0, 0], [10, 0, 0], 0.1)


def test_cv_slider_changes_actual_lineart_without_models(tmp_path):
    import io
    import numpy as np
    from PIL import Image
    from art_artwork_pipeline.pipeline_runner import save_photo, prepare_artwork

    source = np.random.default_rng(19).integers(80, 230, (96, 96, 3), dtype=np.uint8)
    stream = io.BytesIO()
    Image.fromarray(source).save(stream, "PNG")
    results = []
    for job, detail in [("LOW", "0"), ("HIGH", "100")]:
        directory = save_photo(job, stream.getvalue(), tmp_path)
        output = prepare_artwork(
            job,
            stage="LINEART",
            input_path=str(directory / "photo.png"),
            root=tmp_path,
            method="cv",
            detail=detail,
        )
        results.append(np.asarray(Image.open(output["lineart_path"])))
    assert results[0].shape == results[1].shape and np.any(results[0] != results[1])
