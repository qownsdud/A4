"""이동 없이 제어기 상태와 외력 정상 기록을 수집합니다."""

import argparse
import json
import math
import os
from pathlib import Path
import statistics
import time


def summarize(samples):
    if not samples:
        raise ValueError('유효한 힘 측정이 없습니다.')
    if any(len(row) != 6 or not all(math.isfinite(v) for v in row) for row in samples):
        raise ValueError('유효하지 않은 6축 힘 측정입니다.')
    axes = list(zip(*samples))
    bias = [statistics.median(axis) for axis in axes]
    return dict(count=len(samples), force_bias_candidate=bias,
                max_normal_deviation=[max(abs(v-b) for v in axis) for b,axis in zip(bias,axes)])


def main(args=None):
    parser = argparse.ArgumentParser(description='읽기 전용 로봇 점검과 외력 기록. 이동·보호 정지 해제 없음.')
    parser.add_argument('--seconds', type=float, default=10.)
    parser.add_argument('--robot-id', default='dsr01')
    parser.add_argument('--label', default='stationary', help='현재 작업 단계의 이름')
    parser.add_argument('--output', default=str(Path.home()/'A4/data/diagnostics'))
    opt = parser.parse_args(args)
    if not math.isfinite(opt.seconds) or not 1 <= opt.seconds <= 600:
        parser.error('측정 시간은 1~600초입니다.')
    import rclpy
    from dsr_msgs2.srv import GetToolForce, GetRobotState, GetCurrentTool, GetCurrentTcp
    from .driver_events import DriverEventMonitor
    from .live_control import load_settings
    rclpy.init()
    node = rclpy.create_node('a4_inspect_drawing')
    monitor = DriverEventMonitor(node.context, opt.robot_id)
    report = dict(label=opt.label, read_only=True, samples=[], issues=[], units=['N']*3+['Nm']*3,
                  reference='DR_BASE', physical_validation=False)
    clients = {}
    def call(kind, suffix, request):
        if suffix not in clients:
            clients[suffix] = node.create_client(kind, f'/{opt.robot_id}/dsr_controller2/{suffix}')
        client = clients[suffix]
        if not client.wait_for_service(timeout_sec=2):
            raise RuntimeError('서비스 연결 실패: ' + suffix)
        future = client.call_async(request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=2)
        if not future.done() or future.result() is None or not future.result().success:
            raise RuntimeError('관측 응답 실패: ' + suffix)
        return future.result()
    try:
        try:
            monitor.ensure_ready()
            report['alarm_publisher_ready'] = True
        except RuntimeError as exc:
            report['issues'].append(str(exc))
        for name in ('plane_calibration.json', 'pen_slots.json', 'stick_slot.json'):
            path = Path.home()/'.ros'/name
            try:
                json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                report['issues'].append(str(exc))
        try:
            load_settings()
            report['motion_settings_valid'] = True
        except (OSError, ValueError) as exc:
            report['motion_settings_valid'] = False
            report['issues'].append(str(exc))
        report['tool'] = call(GetCurrentTool, 'tool/get_current_tool', GetCurrentTool.Request()).info
        report['tcp'] = call(GetCurrentTcp, 'tcp/get_current_tcp', GetCurrentTcp.Request()).info
        if report['tool'] != os.environ.get('ART_TOOL_NAME','Tool_Weight') or report['tcp'] != os.environ.get('ART_TCP_NAME','GripperDA_v1'):
            report['issues'].append('현재 Tool/TCP가 코드 설정과 다릅니다.')
        start = time.monotonic()
        while time.monotonic()-start < opt.seconds:
            force = list(call(GetToolForce, 'aux_control/get_tool_force', GetToolForce.Request(ref=0)).tool_force)
            if len(force) != 6 or not all(math.isfinite(v) for v in force):
                raise RuntimeError('유효한 6축 힘 관측이 아닙니다.')
            state = call(GetRobotState, 'system/get_robot_state', GetRobotState.Request()).robot_state
            report['samples'].append(dict(elapsed=time.monotonic()-start, force=force, robot_state=state))
            time.sleep(.1)
        report['summary'] = summarize([s['force'] for s in report['samples']])
        if any(s['robot_state'] != 1 for s in report['samples']):
            report['issues'].append('대기 상태가 아닌 측정이 포함됩니다. 기준값으로 자동 채택하지 않습니다.')
        print('측정 완료:', report['summary']['count'], '개. 임계값과 실물 검증 승인은 자동 생성하지 않습니다.')
    except Exception as exc:
        report['issues'].append(str(exc))
    finally:
        generation, reason = monitor.latch.snapshot()
        report['driver_alarm'] = dict(generation=generation, reason=reason)
        directory = Path(opt.output).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory/f'force-{time.time_ns()}.json'
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        print('보고서:', path)
        for issue in report['issues']:
            print('확인 필요:', issue)
        monitor.close()
        node.destroy_node()
        rclpy.shutdown()
    return 1 if not report['samples'] else 0
