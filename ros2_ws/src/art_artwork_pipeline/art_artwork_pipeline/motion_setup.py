"""실물 확인을 받은 제어기 보호 모드를 저장합니다. 로봇 설정은 변경하지 않습니다."""

import argparse
import json
import os
from pathlib import Path


def controller_settings(home_verified, collision_verified):
    if not home_verified or not collision_verified:
        raise ValueError('실제 배치·홈 왕복과 제어기 충돌 감지·보호 정지를 먼저 확인하세요.')
    return dict(validated=True, protection_mode='controller', home_path_verified=True,
                controller_collision_verified=True, motion_timeout=120.,
                position_tolerance=.5, joint_tolerance=.2,
                note='운영자가 확인한 제어기 보호 모드. 소프트웨어 6축 임계값을 사용하지 않습니다. 실물 시험 통과를 의미하지 않습니다.')


def main(args=None):
    parser = argparse.ArgumentParser(description='현장 확인을 바탕으로 제어기 보호 모드 저장. 이동·제어기 변경 없음.')
    parser.add_argument('--home-path-verified', action='store_true')
    parser.add_argument('--controller-collision-verified', action='store_true')
    parser.add_argument('--output', default=os.environ.get('ART_MOTION_CONTROL_CONFIG', str(Path.home()/'.ros/a4_motion_control.json')))
    opt = parser.parse_args(args)
    try:
        data = controller_settings(opt.home_path_verified, opt.controller_collision_verified)
        path = Path(opt.output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc)+'\n')
    print('저장:', path, '\n로봇 이동이나 제어기 안전 설정 변경은 수행하지 않았습니다.')
