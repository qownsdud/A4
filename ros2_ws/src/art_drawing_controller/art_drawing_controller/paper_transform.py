"""종이 mm → 로봇 기준 XYZ. 픽셀 변환과 독립된 순수 좌표 연산입니다."""

import math


def paper_to_robot(point, *, origin, x_axis, y_axis, paper_size_mm=(210.0, 297.0)):
    if any(len(v) != 3 for v in (origin, x_axis, y_axis)) or len(point) != 2:
        raise ValueError("좌표 차원이 잘못되었습니다.")
    if not all(
        math.isfinite(v) for vector in (origin, x_axis, y_axis, point) for v in vector
    ):
        raise ValueError("유한 좌표가 필요합니다.")
    if not (0 <= point[0] <= paper_size_mm[0] and 0 <= point[1] <= paper_size_mm[1]):
        raise ValueError("종이 범위를 벗어납니다.")
    if (
        any(abs(sum(v * v for v in axis) - 1) > 1e-6 for axis in (x_axis, y_axis))
        or abs(sum(a * b for a, b in zip(x_axis, y_axis))) > 1e-6
    ):
        raise ValueError("서로 수직인 단위 축이 필요합니다.")
    return tuple(
        origin[i] + point[0] * x_axis[i] + point[1] * y_axis[i] for i in range(3)
    )


def drawing_pose(point, pen_id, settings, z_delta_mm=0.0):
    """종이 mm의 크기·색상을 바꾸지 않고 기준면 6축 pose로 변환합니다."""
    xyz = paper_to_robot(
        point,
        origin=settings["paper_origin_base_mm"],
        x_axis=settings["paper_x_axis"],
        y_axis=settings["paper_y_axis"],
        paper_size_mm=(settings["paper_mm"]["width"], settings["paper_mm"]["height"]),
    )
    a, b, c = settings["plane_abc"]
    z = a * xyz[0] + b * xyz[1] + c + settings["pen_slots"][pen_id]["z_offset_mm"] + float(z_delta_mm)
    return [xyz[0], xyz[1], z, *settings["orientation_deg"]]
