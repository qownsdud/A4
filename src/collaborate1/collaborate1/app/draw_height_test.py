#!/usr/bin/env python3
"""높이 테스트용 고정 도형 멀티펜 드로잉 노드.

draw_image_standalone.py와 동일한 캘리브레이션·기준막대·중단 복귀 로직을 사용하되,
이미지를 변환하는 대신 안전 직사각형(safe_rect)을 최대한 포괄하는 고정 도형을 그린다:
- 펜 1: 정사각형
- 펜 2: 정삼각형
- 펜 3: 원
"""

import argparse
import json
import math
import os
import sys
from typing import List, Optional, Tuple

from collaborate1.app.draw_image_standalone import (
    CALIBRATION_FILE,
    PENS_FILE,
    RECT_MARGIN_MM,
    STICK_FILE,
    _load_json,
    compute_safe_rect,
    run_robot_drawing,
    save_drawing_preview,
)

# 9점 자동 캘리브레이션 ON/OFF 기본값 (True: ON, False: OFF)
# 실행 시 --cal / --skip-cal 옵션으로 덮어쓸 수 있으며, 이전 실행 설정이 있으면 그 값을 우선 사용합니다.
AUTO_CALIBRATE_9PT = False

Point2D = Tuple[float, float]
HEIGHT_TEST_STATE_FILE = os.path.expanduser("~/.ros/draw_height_test_state.json")


def load_last_auto_calibrate(default: bool) -> bool:
    """이전 실행 시 사용한 9점 캘리브레이션 ON/OFF 설정을 불러온다.
    코드 상의 AUTO_CALIBRATE_9PT 기본값이 변경된 경우에는 새 코드 기본값을 우선한다.
    """
    if not os.path.exists(HEIGHT_TEST_STATE_FILE):
        return default
    try:
        with open(HEIGHT_TEST_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "code_default" not in data or bool(data["code_default"]) != bool(default):
            return default
        if "auto_calibrate" in data:
            return bool(data["auto_calibrate"])
    except (OSError, ValueError, TypeError):
        pass
    return default


def save_last_auto_calibrate(enabled: bool, code_default: bool = AUTO_CALIBRATE_9PT) -> None:
    """이번 실행의 9점 캘리브레이션 ON/OFF 설정을 다음 실행 기본값으로 저장한다."""
    os.makedirs(os.path.dirname(HEIGHT_TEST_STATE_FILE), exist_ok=True)
    with open(HEIGHT_TEST_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"auto_calibrate": bool(enabled), "code_default": bool(code_default)},
            f,
            indent=2,
        )


def build_height_test_pen_groups(
    safe_rect: Tuple[float, float, float, float],
    circle_segments: int = 72,
) -> List[List[List[Point2D]]]:
    """safe_rect를 최대한 채우는 [정사각형, 정삼각형, 원] 펜 그룹을 생성한다."""
    r_min_x, r_max_x, r_min_y, r_max_y = safe_rect
    cx = 0.5 * (r_min_x + r_max_x)
    cy = 0.5 * (r_min_y + r_max_y)
    half_x = 0.5 * (r_max_x - r_min_x)
    half_y = 0.5 * (r_max_y - r_min_y)

    # 1. 펜 1: 정사각형 (safe_rect 내 최대 크기)
    s = min(half_x, half_y)
    square: List[Point2D] = [
        (cx + s, cy + s),
        (cx + s, cy - s),
        (cx - s, cy - s),
        (cx - s, cy + s),
        (cx + s, cy + s),
    ]

    # 2. 펜 2: 정삼각형 (safe_rect 내 최대 크기, 위쪽(+X) 꼭짓점 기준 정방향)
    side_len = min(2.0 * half_y, (4.0 / math.sqrt(3.0)) * half_x)
    tri_h = 0.5 * math.sqrt(3.0) * side_len
    triangle: List[Point2D] = [
        (cx + 0.5 * tri_h, cy),
        (cx - 0.5 * tri_h, cy + 0.5 * side_len),
        (cx - 0.5 * tri_h, cy - 0.5 * side_len),
        (cx + 0.5 * tri_h, cy),
    ]

    # 3. 펜 3: 원 (safe_rect 내 최대 내접원)
    radius = min(half_x, half_y)
    circle: List[Point2D] = [
        (
            cx + radius * math.cos(2.0 * math.pi * i / circle_segments),
            cy + radius * math.sin(2.0 * math.pi * i / circle_segments),
        )
        for i in range(circle_segments + 1)
    ]

    return [[square], [triangle], [circle]]


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="높이 테스트용 고정 도형(정사각형·정삼각형·원) 멀티펜 드로잉")
    parser.add_argument("--dry-run", action="store_true", help="로봇 이동 없이 도형 크기/미리보기만 출력")
    parser.add_argument("--virtual", action="store_true", help="sodvir 가상 모드용 (포스 탐색 생략 후 저장된 평면 높이로 시뮬레이션)")
    cal_group = parser.add_mutually_exclusive_group()
    cal_group.add_argument("--skip-cal", "--no-cal", action="store_true", help="9점 자동 캘리브레이션 OFF (건너뛰기)")
    cal_group.add_argument("--cal", action="store_true", help="9점 자동 캘리브레이션 ON (강제 실행)")
    args, _ = parser.parse_known_args(argv)

    auto_calibrate = load_last_auto_calibrate(AUTO_CALIBRATE_9PT)
    if args.skip_cal:
        auto_calibrate = False
    elif args.cal:
        auto_calibrate = True

    stick_pose = [float(v) for v in _load_json(STICK_FILE, "기준 막대 위치")[:6]]
    pen_data = _load_json(PENS_FILE, "펜 위치")
    if len(pen_data) != 3:
        raise ValueError(f"펜 위치 개수가 3개가 아닙니다: {PENS_FILE}")
    pen_poses = [[float(v) for v in p[:6]] for p in pen_data]

    cal = _load_json(CALIBRATION_FILE, "9점 캘리브레이션")
    cal_points = cal.get("points", [])
    slope_a, slope_b = float(cal.get("a", 0.0)), float(cal.get("b", 0.0))
    safe_rect = compute_safe_rect(cal, RECT_MARGIN_MM)

    pen_groups = build_height_test_pen_groups(safe_rect)
    preview_path, archived_path = save_drawing_preview(pen_groups, safe_rect, "height_test_shapes")

    print(
        f"[높이 테스트 준비 완료] 펜1=정사각형, 펜2=정삼각형, 펜3=원 | "
        f"9점캘리브레이션={'ON' if auto_calibrate else 'OFF'} | "
        f"영역 X=[{safe_rect[0]:.1f}~{safe_rect[1]:.1f}], Y=[{safe_rect[2]:.1f}~{safe_rect[3]:.1f}]"
    )
    print(f"[미리보기 저장] {preview_path}" + (f" (이전 파일 백업: {archived_path})" if archived_path else ""))
    if args.dry_run:
        return

    save_last_auto_calibrate(auto_calibrate)
    run_robot_drawing(
        pen_groups,
        stick_pose,
        pen_poses,
        cal_points,
        slope_a,
        slope_b,
        virtual=args.virtual,
        auto_calibrate=auto_calibrate,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
