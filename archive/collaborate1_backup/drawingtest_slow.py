# 붓펜 보호를 위한 저속-단계적 위치 제어 기반 접촉 탐색

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
TOUCH_VEL, TOUCH_ACC = 2, 2  # 종이 접촉 탐색 속도 (mm/s, mm/s^2)
DRAW_VEL, DRAW_ACC = 10, 10    # 그리기 속도 (mm/s, mm/s^2)

# 자세 및 이동 거리 설정
HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
READY_OFFSET = [0.0, 0.0, -85, 0.0, 0.0, 0.0]  # 홈에서 종이 위 대기 위치까지의 상대 이동
CORNER_LIFT_Z = 1.0                                 # 급격한 방향 전환 시 살짝 들어올릴 높이 (mm)
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

# 붓펜 안전 접촉 탐색 설정
# 주의: 아래 값은 안전성이 검증된 값이 아니다. 펜촉/로봇 설치 조건에서 현장 확인 필요.
# 시작 READY 위치에서 펜촉을 종이 바로 위(비접촉)로 수동 배치한 뒤에만 시험.
ENABLE_DRAWING = False        # 최초 접촉 테스트 전용. 검증하기 전에는 True로 변경 금지.
CONTACT_STEP_MM = 0.2         # 한 번에 내리는 높이 (mm)
CONTACT_MAX_TRAVEL_MM = 1.0   # READY 위치부터 최대 하강량 (mm): 이내에 미감지면 실패
CONTACT_FORCE_DELTA_N = 0.5  # 예시 임계값 (N), 센서 노이즈 측정 후 조정
CONTACT_HARD_LIMIT_N = 1.0   # 예시 중단 임계값 (N), 펜 파손 한계가 아님
CONTACT_CONFIRM_COUNT = 2    # 단일 순간값으로 접촉 결정하지 않음
BASELINE_SAMPLES = 12
SAMPLE_INTERVAL_S = 0.05
CONTACT_SIGN = +1            # 종이 반력 Fz가 증가하면 +1, 감소하면 -1 (시험으로 확인)
CONTACT_RETRACT_MM = 2.0     # 실패 시 비접촉 방향으로 복귀, 안전 공간 확보 필요
# 힘 감지는 매우 부드러운 펜촉의 최초 닿음을 보장하지 않는다.
# 이 구현은 각 movel 완료 시에만 측정한다. 하강 명령 중 실시간 보호 기능이 아니다.

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

def read_fz():
    """Base 기준 측정 외력 Z (N). 통신 오류를 접촉으로 오판하지 않는다."""
    val = float(get_tool_force(DR_BASE)[2])
    if not math.isfinite(val):
        raise RuntimeError("Fz 센서 측정값이 유효하지 않습니다")
    return val


def measure_baseline():
    """종이에 닿지 않은 정지 상태에서 센서 기준값 측정."""
    samples = []
    for _ in range(BASELINE_SAMPLES):
        samples.append(read_fz())
        time.sleep(SAMPLE_INTERVAL_S)
    baseline = sum(samples) / len(samples)
    noise = max(samples) - min(samples)
    node.get_logger().info(f"Fz samples: {[round(v, 3) for v in samples]}")
    node.get_logger().info(f"Baseline Fz={baseline:.3f} N, peak-to-peak noise={noise:.3f} N")
    if noise >= CONTACT_FORCE_DELTA_N / 2:
        raise RuntimeError("센서 노이즈가 감지 임계값에 비해 큽니다. 시험 중단")
    return baseline


def detect_paper_contact():
    """아주 짧은 위치이동 -> 정지 -> 반력 확인. 최대 하강량 초과 시 중단.

    중요: movel 진행 도중에는 Fz 감시가 되지 않는다. 보안/보호 인증 기능이 아니다.
    """
    baseline = measure_baseline()
    moved = 0.0
    hits = 0
    while moved + 1e-9 < CONTACT_MAX_TRAVEL_MM:
        step = min(CONTACT_STEP_MM, CONTACT_MAX_TRAVEL_MM - moved)
        # 실제 종이 위라는 것이 사전 확인된 위치에서만 명령 실행
        movel([0.0, 0.0, -step, 0.0, 0.0, 0.0],
              vel=TOUCH_VEL, acc=TOUCH_ACC, mod=DR_MV_MOD_REL)
        moved += step
        fz = read_fz()
        delta = CONTACT_SIGN * (fz - baseline)
        node.get_logger().info(
            f"Contact probe: dz={moved:.2f}/{CONTACT_MAX_TRAVEL_MM:.2f} mm, "
            f"Fz={fz:.3f} N, signed delta={delta:+.3f} N")
        if delta >= CONTACT_HARD_LIMIT_N:
            raise RuntimeError("외력이 과압 중단 기준에 도달했습니다. 작업 중단")
        if delta >= CONTACT_FORCE_DELTA_N:
            hits += 1
            if hits >= CONTACT_CONFIRM_COUNT:
                node.get_logger().info("Paper reaction detected. Descending stopped.")
                return baseline, moved
        else:
            hits = 0
        time.sleep(SAMPLE_INTERVAL_S)
    raise RuntimeError("최대 하강 거리 안에서 접촉을 확인하지 못했습니다. 작업 중단")


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


def draw_stroke(segments, baseline_fz):
    """검증 후에만 사용: 접촉 감지 높이에서 XY 이동. 세그먼트 사이에 과압 검사.

    동작 중 연속적으로 힘을 제한하지 못하므로 안전이 검증된 힘제어의 대체품이 아니다.
    """
    if not segments:
        return
    current_j6 = align_gripper_to_direction(*segments[0]) if ALIGN_GRIPPER else get_current_posj()[5]
    for idx, (dx, dy) in enumerate(segments):
        if ALIGN_GRIPPER:
            heading_deg = math.degrees(math.atan2(dy, dx))
            target_j6 = select_best_j6(heading_deg, current_j6)
            if abs(target_j6 - current_j6) > CORNER_ANGLE_THRESHOLD:
                # 붓펜 회전은 종이에서 떼고 실시해야 하므로 여기서는 안전하게 중단
                raise RuntimeError("그리퍼 큰 각도 회전이 필요합니다. 붓펜 버전에서 비활성화 필요")
            d_rz = -(target_j6 - current_j6)
            current_j6 = target_j6
        else:
            d_rz = 0.0
        delta_before = CONTACT_SIGN * (read_fz() - baseline_fz)
        if delta_before >= CONTACT_HARD_LIMIT_N:
            raise RuntimeError("그리기 이전 과압 감지. 작업 중단")
        movel([dx, dy, 0.0, 0.0, 0.0, d_rz],
              vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_REL)
        delta_after = CONTACT_SIGN * (read_fz() - baseline_fz)
        if delta_after >= CONTACT_HARD_LIMIT_N:
            raise RuntimeError("그리기 이동 후 과압 감지. 작업 중단")
        node.get_logger().info(f"Segment {idx + 1}/{len(segments)} deltaFz={delta_after:+.3f} N")


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
    if not (0 < CONTACT_FORCE_DELTA_N < CONTACT_HARD_LIMIT_N):
        raise ValueError("임계값 설정이 잘못됐습니다")
    if not (0 < CONTACT_STEP_MM <= CONTACT_MAX_TRAVEL_MM):
        raise ValueError("하강 간격/한계 설정이 잘못됐습니다")
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
        strokes = [[(0.0, 0.0), (SQUARE_SIZE, 0.0),
                    (SQUARE_SIZE, SQUARE_SIZE), (0.0, SQUARE_SIZE), (0.0, 0.0)]]

    # HOME, READY가 충돌 없는 위치인지는 현장 확인 필요.
    movej(homej, vel=J_VEL, acc=J_ACC)
    movel(ready, vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

    # 시험 모드: 한 위치에서 접촉만 확인. 첫 시험에서 그리기 수행하지 않음.
    if not ENABLE_DRAWING:
        baseline, descended = detect_paper_contact()
        node.get_logger().info(
            f"TEST ONLY: contact detected, descended={descended:.2f} mm, "
            f"baseline={baseline:.3f} N. NO DRAWING")
        movel([0.0, 0.0, CONTACT_RETRACT_MM, 0.0, 0.0, 0.0],
              vel=TOUCH_VEL, acc=TOUCH_ACC, mod=DR_MV_MOD_REL)
        return

    # 그림 모드는 현장에서 반력 방향, 노이즈, 위치, 지지대, 안전 정지 검증 후만 사용.
    cur_x, cur_y = 0.0, 0.0
    for s_idx, pts in enumerate(strokes):
        x0, y0 = pts[0]
        if abs(x0 - cur_x) > 0.1 or abs(y0 - cur_y) > 0.1:
            movel([x0 - cur_x, y0 - cur_y, 0.0, 0.0, 0.0, 0.0],
                  vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
        segments = [(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                    for i in range(len(pts) - 1)]
        segments = [(dx, dy) for dx, dy in segments if math.hypot(dx, dy) > 0.05]
        node.get_logger().info(f"Drawing stroke {s_idx + 1}/{len(strokes)} ({len(segments)} segments)")
        descended = 0.0
        try:
            baseline, descended = detect_paper_contact()
            draw_stroke(segments, baseline)
        finally:
            # 검출 중 실제 내려간 양만큼 복귀하여 다음 획의 READY 높이를 유지.
            # 예외가 접촉 탐색 중 발생한 경우 descended가 정의되지 않을 수 있으므로
            # 자동 복구하지 않고 작업 중단 (현장에서 현재 높이 확인 필요).
            if descended > 0:
                movel([0.0, 0.0, descended, 0.0, 0.0, 0.0],
                      vel=TOUCH_VEL, acc=TOUCH_ACC, mod=DR_MV_MOD_REL)
        cur_x, cur_y = pts[-1]
    movel([0.0, 0.0, LIFT_Z, 0.0, 0.0, 0.0],
          vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
    movej(homej, vel=J_VEL, acc=J_ACC)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        node.get_logger().error(f"Drawing aborted: {exc}")
        # 오류 발생 시 추가 자동 이동하지 않는다. 외부 안전 정지/교시기 확인 필요.
        raise
    finally:
        node.destroy_node()
        rclpy.shutdown()
