# 순응/힘 제어 기반 연속 그리기

import rclpy
import DR_init
import time
import math
import os
import re
import xml.etree.ElementTree as ET

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"

# 속도 및 가속도 설정
J_VEL, J_ACC = 60, 60        # Joint 이동 (deg/s, deg/s^2)
L_VEL, L_ACC = 100, 100      # 일반 Linear 이동 (mm/s, mm/s^2)
TOUCH_VEL, TOUCH_ACC = 15, 15  # 종이 접촉 탐색 속도 (mm/s, mm/s^2)
DRAW_VEL, DRAW_ACC = 50, 50    # 그리기 속도 (mm/s, mm/s^2)

# 자세 및 이동 거리 설정
HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
READY_OFFSET = [0.0, 0.0, -85, 0.0, 0.0, 0.0]  # 홈에서 종이 위 대기 위치까지의 상대 이동
CORNER_LIFT_Z = 1.0                                # 급격한 방향 전환 시 살짝 들어올릴 높이 (mm)
STROKE_LIFT_Z = 1.0                                # 다른 획 시작점으로 공중 이동 시 들어올릴 높이 (mm)
LIFT_Z = 30.0                                      # 그리기 완료 후 들어올릴 높이 (mm)
DRAW_MODE = "svg"                                  # "svg", "square", "circle" 중 선택
SVG_FILE = os.path.join(os.path.dirname(__file__), "sample_drawing.svg")
DRAW_AREA_SIZE_MM = 80.0                           # SVG 최대 변을 맞출 작업 영역 크기 (mm)
CURVE_STEP_MM = 3.0                                # SVG 곡선/원 샘플링 간격 (mm)
SQUARE_SIZE = 50.0                                 # 그릴 사각형 한 변 길이 (mm)
CIRCLE_RADIUS = 25.0                               # 그릴 원 반지름 (mm)
CIRCLE_STEPS = 72                                  # 원 분할 수 (많을수록 부드러운 곡선)
CORNER_ANGLE_THRESHOLD = 25.0                      # 이 각도(deg) 이하 회전은 펜을 떼지 않고 연속 회전
ALIGN_GRIPPER = False                              # True: 진행 방향 회전 정렬 / False: 회전 없이 그리기
GRIPPER_AXIS_OFFSET_DEG = 0.0                      # HOME 상태에서 그리퍼 손가락 방향 오프셋 (X축=0.0, Y축=90.0)
J6_LIMIT_DEG = 360.0                               # 그리퍼(J6) 회전 허용 범위 (-180 ~ +180도)

# 순응 제어 및 자동 힘 캘리브레이션 파라미터
COMPLIANCE_STX = [3000.0, 3000.0, 400.0, 200.0, 200.0, 200.0]  # XY는 단단하게, Z는 유연하게
AUTO_FORCE_START = -5.0      # 최소 하강 힘 자동 탐색 시작값 (N)
AUTO_FORCE_STEP = -1.0       # 탐색 시 힘 증가 단위 (N)
AUTO_FORCE_MAX = -14.0       # 탐색 최대 한계 (N)
AUTO_FORCE_MOVE_MM = 1.0     # 하강 시작 판정 최소 이동 거리 (mm)
DRAW_PRELOAD_Z = -1.5        # 접촉 후 힘 제어 해제 상태에서 순응 스프링으로 누를 깊이 (mm, 400N/m 기준 ~0.6N)
TOUCH_SETTLE_TIME = 0.8      # 힘 제어 시작 후 등속 하강 안정화 대기 시간 (s)
TOUCH_BASELINE_SAMPLES = 5   # 등속 하강 중 moving_baseline 평균 샘플 수
TOUCH_FORCE_THRESHOLD = 1.5  # 등속 하강 기준값 대비 접촉 판정 +Z 외력 증가량 (N)
TOUCH_CONFIRM_COUNT = 3      # 노이즈 스파이크 방지용 연속 초과 횟수
TOUCH_TIMEOUT = 30.0         # 힘 제어 하강 최대 대기 시간 (s)
FORCE_RAMP_TIME = 0.3        # 목표 힘 도달 시간 (s)

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init(args=None)
node = rclpy.create_node("rokey_gear", namespace=ROBOT_ID)
DR_init.__dsr__node = node

try:
    from DSR_ROBOT2 import (
        set_tool,
        set_tcp,
        movej,
        movel,
        amovel,
        move_periodic,
        amove_periodic,
        task_compliance_ctrl,
        set_stiffnessx,
        release_compliance_ctrl,
        set_desired_force,
        release_force,
        set_digital_output,
        get_current_posj,
        get_current_posx,
        get_tool_force,
        check_force_condition,
        DR_MV_MOD_REL,
        DR_MV_MOD_ABS,
        DR_FC_MOD_REL,
        DR_FC_MOD_ABS,
        DR_AXIS_Z,
        DR_BASE,
        DR_TOOL,
    )
    from DR_common2 import posx, posj
except ImportError as e:
    node.get_logger().error(f"Error importing DSR_ROBOT2 : {e}")
    raise

def wait_paper_contact(force_threshold=TOUCH_FORCE_THRESHOLD, timeout=TOUCH_TIMEOUT):
    """등속 하강 중 이동 마찰 기준값(moving_baseline)을 잡아, 그 대비 미약한 접촉력도 감지한다."""
    start = time.time()

    # 1. 초기 가감속/힘 증가 구간 안정화 대기
    time.sleep(TOUCH_SETTLE_TIME)

    # 2. 허공 등속 하강 상태의 Fz 평균을 이동 기준값으로 측정 (이동 마찰 오프셋 상쇄)
    samples = []
    for _ in range(TOUCH_BASELINE_SAMPLES):
        samples.append(get_tool_force(DR_BASE)[2])
        time.sleep(0.05)
    moving_baseline = sum(samples) / len(samples)
    node.get_logger().info(f"Moving baseline Fz = {moving_baseline:.2f} N")

    # 3. moving_baseline 대비 연속 N회 이상 힘 변화가 감지되면 접촉 확정
    hit_count = 0
    while time.time() - start < timeout:
        fz = get_tool_force(DR_BASE)[2]
        delta_fz = fz - moving_baseline
        node.get_logger().info(f"Descending... Fz={fz:.2f} N (delta={delta_fz:+.2f} N)")
        if delta_fz >= force_threshold:
            hit_count += 1
            if hit_count >= TOUCH_CONFIRM_COUNT:
                node.get_logger().info(f"Paper contact detected! (delta={delta_fz:+.2f} N)")
                return True
        else:
            hit_count = 0
        time.sleep(0.05)
    node.get_logger().warn("Paper contact timeout")
    return False


def select_best_j6(heading_deg, current_j6):
    """그리퍼 대칭성(180도)을 이용해 -180~+180도 범위 내 최단 J6 목표 각도를 고른다.
    HOME 자세에서 Tool +Z가 Base -Z를 향하므로 Base 반시계(+heading)는 J6 음수(-) 방향이다.
    """
    base_j6 = (-(heading_deg + GRIPPER_AXIS_OFFSET_DEG)) % 180.0
    candidates = [
        base_j6 + 180.0 * k
        for k in range(-2, 3)
        if -J6_LIMIT_DEG <= base_j6 + 180.0 * k <= J6_LIMIT_DEG
    ]
    return min(candidates, key=lambda c: (round(abs(c - current_j6), 3), abs(c)))


def align_gripper_to_direction(dx, dy):
    """공중에서 진행 방향(dx, dy)에 그리퍼 손가락 축이 일치하도록 J6을 회전한다."""
    heading_deg = math.degrees(math.atan2(dy, dx))
    joints = list(get_current_posj())
    best_j6 = select_best_j6(heading_deg, joints[5])
    if abs(best_j6 - joints[5]) > 1.0:
        joints[5] = best_j6
        node.get_logger().info(f"Aligning gripper J6 -> {best_j6:.1f} deg")
        movej(posj(joints), vel=J_VEL, acc=J_ACC)
    return best_j6


def make_circle_segments(radius=CIRCLE_RADIUS, steps=CIRCLE_STEPS):
    """중심 기준 원 경로를 상대 이동 (dx, dy) 리스트로 생성한다."""
    segments = []
    prev_x, prev_y = radius, 0.0
    for i in range(1, steps + 1):
        theta = 2.0 * math.pi * i / steps
        nx, ny = radius * math.cos(theta), radius * math.sin(theta)
        segments.append((nx - prev_x, ny - prev_y))
        prev_x, prev_y = nx, ny
    return segments


def calibrate_min_descent_force():
    """시작 시 공중에서 정지마찰을 넘어 실제로 -Z 하강이 시작되는 최소 힘을 자동 탐색한다."""
    start_z = get_current_posx(DR_BASE)[0][2]
    detected_force = -10.0

    task_compliance_ctrl(stx=COMPLIANCE_STX)
    try:
        time.sleep(0.4)
        force = AUTO_FORCE_START
        while force >= AUTO_FORCE_MAX:
            set_desired_force(
                [0.0, 0.0, force, 0.0, 0.0, 0.0],
                dir=[0, 0, 1, 0, 0, 0],
                time=0.2,
                mod=DR_FC_MOD_REL,
            )
            time.sleep(0.4)
            cur_z = get_current_posx(DR_BASE)[0][2]
            moved = start_z - cur_z
            node.get_logger().info(f"Auto-force probe: force={force:.1f} N, dz={moved:+.2f} mm")
            if moved >= AUTO_FORCE_MOVE_MM:
                detected_force = force
                break
            force += AUTO_FORCE_STEP
    finally:
        release_force()
        release_compliance_ctrl()

    # 탐색 중 내려간 만큼 원래 ready 높이로 복귀
    end_z = get_current_posx(DR_BASE)[0][2]
    if start_z - end_z > 0.2:
        movel([0.0, 0.0, start_z - end_z, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
    node.get_logger().info(f"Calibrated min descent force = {detected_force:.1f} N")
    return detected_force


def draw_stroke(segments, touch_force_z):
    """자동 탐색된 최소 하강 힘(touch_force_z)을 유지해 펜촉이 종이에서 떨어지지 않도록 그린다."""
    if not segments:
        return

    current_j6 = align_gripper_to_direction(*segments[0]) if ALIGN_GRIPPER else get_current_posj()[5]
    in_contact = False

    def start_contact():
        nonlocal in_contact
        task_compliance_ctrl(stx=COMPLIANCE_STX)
        time.sleep(0.5)
        set_desired_force(
            [0.0, 0.0, touch_force_z, 0.0, 0.0, 0.0],
            dir=[0, 0, 1, 0, 0, 0],
            time=FORCE_RAMP_TIME,
            mod=DR_FC_MOD_REL,
        )
        in_contact = wait_paper_contact()
        return in_contact

    def stop_contact(lift=True):
        nonlocal in_contact
        release_force()
        release_compliance_ctrl()
        in_contact = False
        if lift:
            movel([0.0, 0.0, CORNER_LIFT_Z, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

    try:
        if not start_contact():
            return

        for idx, (dx, dy) in enumerate(segments):
            if ALIGN_GRIPPER:
                heading_deg = math.degrees(math.atan2(dy, dx))
                target_j6 = select_best_j6(heading_deg, current_j6)
                d_j6 = target_j6 - current_j6

                # 급격한 각도 변화(꼭짓점)나 J6 한계 반전이 필요할 때만 살짝 들고 회전
                if abs(d_j6) > CORNER_ANGLE_THRESHOLD:
                    stop_contact(lift=True)
                    current_j6 = align_gripper_to_direction(dx, dy)
                    if not start_contact():
                        break
                    d_rz = 0.0
                else:
                    # Base +Z 회전(d_rz)은 J6 회전(d_j6)과 부호가 반대
                    d_rz = -d_j6
                    current_j6 = target_j6
            else:
                d_rz = 0.0

            movel([dx, dy, 0.0, 0.0, 0.0, d_rz], vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_REL)
            if (idx + 1) % 10 == 0 or idx == len(segments) - 1:
                node.get_logger().info(f"Segment {idx + 1}/{len(segments)} Fz={get_tool_force(DR_BASE)[2]:.2f} N")
    finally:
        release_force()
        release_compliance_ctrl()


def _sample_cubic(p0, p1, p2, p3, step_mm=CURVE_STEP_MM):
    """3차 베지어 곡선을 step_mm 간격의 점 리스트로 샘플링한다."""
    chord = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
    ctrl = (
        math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        + math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        + math.hypot(p3[0] - p2[0], p3[1] - p2[1])
    )
    n = max(4, int(math.ceil(max(chord, ctrl) / step_mm)))
    pts = []
    for i in range(1, n + 1):
        t = i / n
        u = 1.0 - t
        x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def _parse_svg_path(d_str):
    """SVG path d 문자열(M/m, L/l, H/h, V/v, C/c, Q/q, Z/z)을 획(점 리스트) 목록으로 변환한다."""
    tokens = re.findall(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", d_str)
    strokes = []
    cur_stroke = []
    cx, cy = 0.0, 0.0
    sx, sy = 0.0, 0.0
    cmd = None
    i = 0

    def next_float():
        nonlocal i
        val = float(tokens[i])
        i += 1
        return val

    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in ("Z", "z"):
                if cur_stroke:
                    cur_stroke.append((sx, sy))
                    cx, cy = sx, sy
                continue
        if cmd in ("M", "m"):
            x, y = next_float(), next_float()
            if cmd == "m":
                x += cx
                y += cy
            if len(cur_stroke) > 1:
                strokes.append(cur_stroke)
            cx, cy = x, y
            sx, sy = x, y
            cur_stroke = [(cx, cy)]
            cmd = "L" if cmd == "M" else "l"
        elif cmd in ("L", "l"):
            x, y = next_float(), next_float()
            if cmd == "l":
                x += cx
                y += cy
            cx, cy = x, y
            cur_stroke.append((cx, cy))
        elif cmd in ("H", "h"):
            x = next_float() + (cx if cmd == "h" else 0.0)
            cx = x
            cur_stroke.append((cx, cy))
        elif cmd in ("V", "v"):
            y = next_float() + (cy if cmd == "v" else 0.0)
            cy = y
            cur_stroke.append((cx, cy))
        elif cmd in ("C", "c"):
            x1, y1 = next_float(), next_float()
            x2, y2 = next_float(), next_float()
            x3, y3 = next_float(), next_float()
            if cmd == "c":
                x1, y1 = cx + x1, cy + y1
                x2, y2 = cx + x2, cy + y2
                x3, y3 = cx + x3, cy + y3
            cur_stroke.extend(_sample_cubic((cx, cy), (x1, y1), (x2, y2), (x3, y3)))
            cx, cy = x3, y3
        elif cmd in ("Q", "q"):
            qx, qy = next_float(), next_float()
            x, y = next_float(), next_float()
            if cmd == "q":
                qx, qy = cx + qx, cy + qy
                x, y = cx + x, cy + y
            c1 = (cx + 2.0 / 3.0 * (qx - cx), cy + 2.0 / 3.0 * (qy - cy))
            c2 = (x + 2.0 / 3.0 * (qx - x), y + 2.0 / 3.0 * (qy - y))
            cur_stroke.extend(_sample_cubic((cx, cy), c1, c2, (x, y)))
            cx, cy = x, y
        else:
            i += 1
    if len(cur_stroke) > 1:
        strokes.append(cur_stroke)
    return strokes


def load_svg_strokes(svg_path, area_size_mm=DRAW_AREA_SIZE_MM, step_mm=CURVE_STEP_MM):
    """SVG 파일을 읽어 로봇 중심 (0, 0) 기준 mm 단위 획(점 리스트) 목록으로 변환한다."""
    tree = ET.parse(svg_path)
    root = tree.getroot()

    vb = root.attrib.get("viewBox")
    if vb:
        vx, vy, vw, vh = [float(v) for v in re.split(r"[\s,]+", vb.strip())]
    else:
        vx, vy, vw, vh = 0.0, 0.0, 100.0, 100.0

    scale = area_size_mm / max(vw, vh)
    cx_vb, cy_vb = vx + vw / 2.0, vy + vh / 2.0

    raw_strokes = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "rect":
            x = float(elem.attrib.get("x", 0.0))
            y = float(elem.attrib.get("y", 0.0))
            w = float(elem.attrib.get("width", 0.0))
            h = float(elem.attrib.get("height", 0.0))
            raw_strokes.append([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)])
        elif tag == "circle":
            cx = float(elem.attrib.get("cx", 0.0))
            cy = float(elem.attrib.get("cy", 0.0))
            r = float(elem.attrib.get("r", 0.0))
            n = max(16, int(math.ceil(2.0 * math.pi * r * scale / step_mm)))
            raw_strokes.append([
                (cx + r * math.cos(2.0 * math.pi * k / n), cy + r * math.sin(2.0 * math.pi * k / n))
                for k in range(n + 1)
            ])
        elif tag == "line":
            raw_strokes.append([
                (float(elem.attrib.get("x1", 0.0)), float(elem.attrib.get("y1", 0.0))),
                (float(elem.attrib.get("x2", 0.0)), float(elem.attrib.get("y2", 0.0))),
            ])
        elif tag in ("polyline", "polygon"):
            nums = [float(v) for v in re.findall(r"[-+]?(?:\d*\.\d+|\d+)", elem.attrib.get("points", ""))]
            pts = [(nums[k], nums[k + 1]) for k in range(0, len(nums) - 1, 2)]
            if tag == "polygon" and pts:
                pts.append(pts[0])
            if len(pts) > 1:
                raw_strokes.append(pts)
        elif tag == "path":
            raw_strokes.extend(_parse_svg_path(elem.attrib.get("d", "")))

    # SVG Y축(아래 방향)을 로봇 Base Y축(위 방향)으로 반전하고 중심 (0, 0)으로 정렬
    mm_strokes = []
    for stroke in raw_strokes:
        pts_mm = [((x - cx_vb) * scale, -(y - cy_vb) * scale) for x, y in stroke]
        if len(pts_mm) > 1:
            mm_strokes.append(pts_mm)
    return mm_strokes


def main():
    set_tool(TOOL_NAME)
    set_tcp(TCP_NAME)

    homej = posj(HOME_JOINTS)
    ready = posx(READY_OFFSET)

    if DRAW_MODE == "svg":
        strokes = load_svg_strokes(SVG_FILE)
        node.get_logger().info(f"Loaded {len(strokes)} strokes from {SVG_FILE}")
    elif DRAW_MODE == "circle":
        pts = [(CIRCLE_RADIUS, 0.0)]
        for dx, dy in make_circle_segments():
            pts.append((pts[-1][0] + dx, pts[-1][1] + dy))
        strokes = [pts]
    else:
        strokes = [[
            (0.0, 0.0),
            (SQUARE_SIZE, 0.0),
            (SQUARE_SIZE, SQUARE_SIZE),
            (0.0, SQUARE_SIZE),
            (0.0, 0.0),
        ]]

    movej(homej, vel=J_VEL, acc=J_ACC)
    movel(ready, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

    touch_force_z = calibrate_min_descent_force()

    cur_x, cur_y = 0.0, 0.0
    for s_idx, pts in enumerate(strokes):
        x0, y0 = pts[0]
        # 공중에서 다음 획의 시작점 (x0, y0)으로 이동
        if abs(x0 - cur_x) > 0.1 or abs(y0 - cur_y) > 0.1:
            movel([x0 - cur_x, y0 - cur_y, 0.0, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

        segments = [(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1)]
        segments = [(dx, dy) for dx, dy in segments if math.hypot(dx, dy) > 0.05]
        node.get_logger().info(f"Drawing stroke {s_idx + 1}/{len(strokes)} ({len(segments)} segments)")
        draw_stroke(segments, touch_force_z)
        cur_x, cur_y = pts[-1]

        # 다음 획 이동을 위해 펜 들어올림
        if s_idx < len(strokes) - 1:
            movel([0.0, 0.0, STROKE_LIFT_Z, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

    movel([0.0, 0.0, LIFT_Z, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
    movej(homej, vel=J_VEL, acc=J_ACC)