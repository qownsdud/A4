"""중단된 실행 세션을 정리하기 위한 프로세스·실제 정지 관측 검사."""

import math
import os
from pathlib import Path
import time


def assert_no_other_workers(script_name='draw_image_standalone.py'):
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            args = (entry/'cmdline').read_bytes().decode(errors='replace').split('\0')
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            raise RuntimeError('드로잉 프로세스 검사 권한이 없습니다.') from exc
        if any(Path(arg).name in {script_name,'standalone_drawer'} for arg in args if arg):
            raise RuntimeError('다른 드로잉 실행 프로세스가 남아 있습니다: PID '+entry.name)


def verify_stationary(read, delay=.05):
    previous = None
    for _ in range(3):
        sample = read()
        pose, vel = sample['pose'], sample['velocity']
        if sample['state'] != 1 or sample['motion'] != 0:
            raise RuntimeError('로봇이 정상 대기·이동 종료 상태가 아닙니다. 티치펜던트에서 확인하세요.')
        if any(len(values)!=6 or not all(math.isfinite(float(v)) for v in values) for values in (pose,vel)):
            raise RuntimeError('정지 관측값이 유효하지 않습니다.')
        if any(abs(v)>=.01 for v in vel) or previous and max(abs(a-b) for a,b in zip(previous,pose))>.1:
            raise RuntimeError('로봇의 실제 정지가 확인되지 않았습니다.')
        previous=list(pose)
        time.sleep(delay)
