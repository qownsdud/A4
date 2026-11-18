"""짧은 제어기 알람의 유지·초기화 경쟁 조건과 읽기 전용 통계를 확인합니다."""

from types import SimpleNamespace
import pytest
from art_artwork_pipeline.driver_events import DriverAlarmLatch
from art_artwork_pipeline.inspect_drawing import summarize
from art_artwork_pipeline.live_control import ForceStopped, LiveControl


def alarm(code=7060, level=3, group=5):
    return SimpleNamespace(code=code, level=level, group=group, msg1='시험 알람', msg2='', msg3='')


def test_alarm_survives_return_to_standby_and_only_explicit_ack_clears():
    latch = DriverAlarmLatch()
    latch.receive(alarm())
    generation, reason = latch.snapshot()
    api = SimpleNamespace(state=lambda: 1, alarm_snapshot=latch.snapshot)
    control = LiveControl('ALARM', 10., 1, {}, emit=lambda e: None)
    control.api = api
    with pytest.raises(ForceStopped, match='7060'):
        control.check()
    assert reason and latch.snapshot()[1]
    latch.acknowledge(generation)
    control.check()


def test_reset_does_not_clear_alarm_received_during_recovery():
    latch = DriverAlarmLatch()
    latch.receive(alarm())
    generation, _ = latch.snapshot()
    latch.receive(alarm(code=7067))
    with pytest.raises(RuntimeError, match='새 제어기 알람'):
        latch.acknowledge(generation)
    assert '7067' in latch.snapshot()[1]


def test_info_is_not_fault_but_safety_warning_is():
    latch = DriverAlarmLatch()
    latch.receive(alarm(level=1))
    latch.receive(alarm(level=2, group=2))
    assert latch.snapshot() == (0, '')
    latch.receive(alarm(level=2))
    assert latch.snapshot()[1]


def test_recording_statistics_are_not_a_safety_threshold():
    summary = summarize([[1.,2.,3.,4.,5.,6.], [3.,4.,5.,6.,7.,8.]])
    assert summary['force_bias_candidate'] == [2.,3.,4.,5.,6.,7.]
    assert summary['max_normal_deviation'] == [1.]*6
    assert 'force_limits' not in summary and 'validated' not in summary
    with pytest.raises(ValueError):
        summarize([[float('nan')]*6])


def test_real_ros_alarm_topic_latches_after_publisher_returns_normal():
    import os
    import time
    if os.environ.get('ROS_DOMAIN_ID') != '99':
        pytest.skip('시험 도메인 99가 필요합니다.')
    import rclpy
    from dsr_msgs2.msg import RobotError
    from art_artwork_pipeline.driver_events import DriverEventMonitor
    rclpy.init()
    node = rclpy.create_node('test_alarm_publisher')
    publisher = node.create_publisher(RobotError, '/test_robot/error', 100)
    monitor = DriverEventMonitor(node.context, 'test_robot')
    try:
        monitor.ensure_ready()
        end = time.monotonic()+3
        while publisher.get_subscription_count() != 1 and time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=.02)
        assert publisher.get_subscription_count() == 1
        publisher.publish(RobotError(level=3, group=5, code=7060, msg1='시험 충돌'))
        end = time.monotonic()+3
        while not monitor.latch.snapshot()[1] and time.monotonic() < end:
            time.sleep(.02)
        generation, reason = monitor.latch.snapshot()
        assert '7060' in reason
        publisher.publish(RobotError(level=1, group=1, code=0, msg1='정상 안내'))
        time.sleep(.05)
        assert monitor.latch.snapshot() == (generation, reason)
        monitor.latch.acknowledge(generation)
        assert monitor.latch.snapshot()[1] == ''
    finally:
        monitor.close()
        node.destroy_node()
        rclpy.shutdown()


def test_controller_mode_requires_real_confirmations_and_no_fake_force_limits(tmp_path):
    import json
    from art_artwork_pipeline.motion_setup import controller_settings
    from art_artwork_pipeline.live_control import load_settings
    with pytest.raises(ValueError):
        controller_settings(True, False)
    data = controller_settings(True, True)
    path = tmp_path/'control.json'
    path.write_text(json.dumps(data))
    settings = load_settings(path)
    assert settings['protection_mode'] == 'controller'
    assert 'force_limits' not in settings
    api = SimpleNamespace(state=lambda: 1, force=lambda:[0.]*6, alarm_snapshot=lambda: (0,''))
    c = LiveControl('CONTROLLER', 10., 1, settings, emit=lambda event: None)
    c.api = api
    c.sensing = True
    c.check()
    api.alarm_snapshot = lambda: (1,'시험 충돌')
    with pytest.raises(ForceStopped):
        c.check()
    data['controller_collision_verified'] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_settings(path)


def test_controller_alarm_holds_execution_until_operator_reset():
    import threading
    from test_live_control import wait, close
    from robot_worker_fixture import FakeApi, execute
    from art_artwork_pipeline.motion_setup import controller_settings
    latch = DriverAlarmLatch()
    class Api(FakeApi):
        alarm_snapshot = lambda self: latch.snapshot()
        acknowledge_alarm = lambda self, generation: latch.acknowledge(generation)
    api = Api()
    c = LiveControl('BODY_CONTACT', 100., 1, controller_settings(True, True), emit=lambda e: None)
    c.bind(api, api.home, lambda current: 50.)
    worker = threading.Thread(target=execute, args=(c, api, [dict(points_mm=[[0.,0.],[100.,0.]],pen_id='PEN_1')]))
    worker.start()
    try:
        wait(lambda: api.current[2]==0 and api.current[0]>0)
        latch.receive(alarm())
        wait(lambda: c.state=='FORCE_STOPPED')
        assert api.state()==1 and c.force_latched and api.stops>0
        c.request('RESUME','RESUME')
        wait(lambda: c.state=='COMPLETED')
        assert latch.snapshot()[1]=='' and not c.force_latched
    finally:
        close(c,worker)


def test_recovery_rejects_moving_protected_or_invalid_observations():
    from art_artwork_pipeline.execution_recovery import verify_stationary
    valid=dict(state=1,motion=0,pose=[0.]*6,velocity=[0.]*6)
    verify_stationary(lambda:valid,delay=0)
    for sample in (dict(valid,state=2),dict(valid,state=3),dict(valid,motion=2),
                   dict(valid,velocity=[1.]*6),dict(valid,pose=[float('nan')]*6)):
        with pytest.raises(RuntimeError):
            verify_stationary(lambda:sample,delay=0)
    values=iter([valid,dict(valid,pose=[2.]*6)])
    with pytest.raises(RuntimeError):
        verify_stationary(lambda:next(values),delay=0)
