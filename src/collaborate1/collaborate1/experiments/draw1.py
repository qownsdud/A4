"""펜 높이 조절 테스트 노드 (붓펜 + 측면 막대기 접촉 감지 방식).

동작 순서:
1. 현재 위치(종이 위 대기 상태)에서 정지 상태 기준 외력(Fz) 측정
2. 붓펜 옆 막대기가 바닥에 닿을 때까지 소폭 하강하며 외력 감지 후 즉시 멈춤
3. 막대기 접촉 높이에서 지정한 높이(LIFT_AFTER_STICK_MM)만큼 상승해 붓펜 높이 맞춤
4. 붓펜으로 저속·부드러운 가감속으로 스무스하게 테스트 경로 그리기 후 복귀
"""

import math
import time
import rclpy
import DR_init

from collaborate1.core.run_logger import RunLogSession

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
TOOL_NAME = "Tool_Weight"
TCP_NAME = "GripperDA_v1"

# --- 속도 / 가속도 설정 ---
J_VEL, J_ACC = 60, 60            # Joint 이동 (deg/s, deg/s^2)
L_VEL, L_ACC = 50, 50            # 일반 Linear 이동 (mm/s, mm/s^2)
PROBE_VEL, PROBE_ACC = 5, 5      # 막대기 접촉 탐색 속도 (mm/s, mm/s^2)
DRAW_VEL, DRAW_ACC = 15, 15      # 붓펜 스무스 그리기 속도 (mm/s, mm/s^2)

# --- 시작 위치 설정 ---
# False(권장): 현재 조그/티칭으로 종이 바로 위에 위치시킨 상태에서 즉시 테스트 시작
# True: HOME_JOINTS -> READY_OFFSET 이동 후 테스트 시작
USE_HOME_READY = False
HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
READY_OFFSET = [0.0, 0.0, -90.0, 0.0, 0.0, 0.0]

# --- 1단계: 막대기 바닥 접촉 감지 파라미터 ---
PROBE_STEP_MM = 0.5              # 1회 하강 간격 (mm)
PROBE_MAX_TRAVEL_MM = 20.0       # 최대 하강 허용 거리 (mm)
WARMUP_STEPS = 2                 # 첫 하강 시 관절 마찰 오프셋 안정화용 워밍업 스텝 수
SETTLE_TIME_S = 0.12             # 각 이동 정지 후 진동 안정화 대기 시간 (s)
READ_SAMPLES = 3                 # 1회 외력 측정 시 평균낼 샘플 수
CONTACT_FORCE_DELTA_N = 2.5      # 막대기 접촉 판정 외력 변화량 (N)
HARD_LIMIT_FORCE_N = 30.0         # 과압 즉시 중단 한계 (N)
CONFIRM_COUNT = 2                # 노이즈 오판 방지용 연속 감지 횟수
BASELINE_SAMPLES = 10            # 정지 상태 기준 외력 샘플 수
SAMPLE_INTERVAL_S = 0.03         # 샘플링 주기 (s)
CONTACT_SIGN = +1                # 바닥 반력 Fz가 증가하면 +1, 감소하면 -1

# --- 2단계: 막대기 접촉 후 붓펜 그리기 높이 조절 파라미터 ---
LIFT_AFTER_STICK_MM = 2        # 막대기 멈춘 높이에서 다시 올라갈 높이 (mm)

# --- 3단계: 붓펜 스무스 그리기 테스트 파라미터 ---
ENABLE_DRAWING = True            # False면 높이 조절만 확인하고 그리기 생략
DRAW_SHAPE = "line"              # "line" (직선) 또는 "square" (사각형)
TEST_DRAW_LENGTH_MM = 50.0       # 테스트 그리기 길이 (mm)
END_LIFT_MM = 30.0               # 그리기 완료 후 들어올릴 높이 (mm)

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init(args=None)
node = rclpy.create_node("draw1_height_test", namespace=ROBOT_ID)
DR_init.__dsr__node = node

try:
    from DSR_ROBOT2 import (
        set_tool,
        set_tcp,
        movej,
        movel,
        get_current_posx,
        get_tool_force,
        DR_MV_MOD_REL,
        DR_BASE,
    )
    from DR_common2 import posx, posj
except ImportError as e:
    node.get_logger().error(f"Error importing DSR_ROBOT2: {e}")
    raise


def read_fz() -> float:
    """Base 기준 외력 Z(N)를 읽고 유효성을 검사한다."""
    val = float(get_tool_force(DR_BASE)[2])
    if not math.isfinite(val):
        raise RuntimeError("Fz 센서 측정값이 유효하지 않습니다.")
    return val


def read_fz_avg(samples: int = READ_SAMPLES) -> float:
    """짧은 간격으로 여러 번 읽어 평균낸 외력 Z(N)를 반환한다."""
    vals = []
    for i in range(samples):
        vals.append(read_fz())
        if i < samples - 1:
            time.sleep(SAMPLE_INTERVAL_S)
    return sum(vals) / len(vals)


def measure_baseline() -> float:
    """비접촉 정지 상태에서 기준 외력(Fz)과 노이즈 폭을 측정한다."""
    samples = []
    for _ in range(BASELINE_SAMPLES):
        samples.append(read_fz())
        time.sleep(SAMPLE_INTERVAL_S)
    baseline = sum(samples) / len(samples)
    noise = max(samples) - min(samples)
    node.get_logger().info(
        f"[초기화] Baseline Fz={baseline:.3f} N, noise={noise:.3f} N"
    )
    if noise >= CONTACT_FORCE_DELTA_N:
        raise RuntimeError(
            f"센서 노이즈({noise:.3f} N)가 접촉 판정 기준({CONTACT_FORCE_DELTA_N} N) 이상입니다."
        )
    return baseline


def probe_stick_contact(baseline_fz: float) -> tuple[float, float]:
    """막대기가 바닥에 닿아 외력이 발생할 때까지 하강하고 멈춘다.

    첫 하강 직후 발생하는 관절 마찰 오프셋을 배제하기 위해 WARMUP_STEPS 이후
    하강 중 기준값(probe_baseline)을 새로 잡아 그 대비 외력 증가를 감지한다.

    Returns:
        (접촉 시점의 Z 좌표, 총 하강 거리 mm)
    """
    descended = 0.0
    step_idx = 0
    hits = 0
    probe_baseline = None
    node.get_logger().info("[1단계] 막대기 바닥 접촉 탐색 시작")

    while descended + 1e-9 < PROBE_MAX_TRAVEL_MM:
        step = min(PROBE_STEP_MM, PROBE_MAX_TRAVEL_MM - descended)
        movel([0.0, 0.0, -step, 0.0, 0.0, 0.0], vel=PROBE_VEL, acc=PROBE_ACC, mod=DR_MV_MOD_REL)
        descended += step
        step_idx += 1

        time.sleep(SETTLE_TIME_S)
        cur_fz = read_fz_avg()

        # 워밍업 중에도 초기 기준 대비 급격한 과압은 즉시 차단
        raw_delta = CONTACT_SIGN * (cur_fz - baseline_fz)
        if raw_delta >= HARD_LIMIT_FORCE_N:
            raise RuntimeError(
                f"과압 감지(raw deltaFz={raw_delta:+.3f} N >= {HARD_LIMIT_FORCE_N} N). 즉시 중단합니다."
            )

        if step_idx <= WARMUP_STEPS:
            node.get_logger().info(
                f"워밍업 하강 {descended:.2f} mm | Fz={cur_fz:.3f} N (초기 대비 {raw_delta:+.3f} N)"
            )
            if step_idx == WARMUP_STEPS:
                probe_baseline = cur_fz
                node.get_logger().info(
                    f"[1단계] 하강 기준값(probe_baseline) 설정: {probe_baseline:.3f} N"
                )
            continue

        delta = CONTACT_SIGN * (cur_fz - probe_baseline)
        node.get_logger().info(
            f"하강 {descended:.2f}/{PROBE_MAX_TRAVEL_MM:.2f} mm | Fz={cur_fz:.3f} N, deltaFz={delta:+.3f} N"
        )

        if delta >= HARD_LIMIT_FORCE_N:
            raise RuntimeError(
                f"과압 감지(deltaFz={delta:+.3f} N >= {HARD_LIMIT_FORCE_N} N). 즉시 중단합니다."
            )

        if delta >= CONTACT_FORCE_DELTA_N:
            hits += 1
            if hits >= CONFIRM_COUNT:
                contact_z = float(get_current_posx(DR_BASE)[0][2])
                node.get_logger().info(
                    f"[1단계 완료] 막대기 바닥 접촉 감지! 정지 Z={contact_z:.2f} mm (하강 {descended:.2f} mm)"
                )
                return contact_z, descended
        else:
            hits = 0

    raise RuntimeError(
        f"최대 하강 거리({PROBE_MAX_TRAVEL_MM} mm) 내에서 막대기 접촉을 감지하지 못했습니다."
    )


def adjust_height_for_brush(lift_mm: float) -> float:
    """막대기가 닿아 멈춘 높이에서 붓펜 그리기에 알맞게 조금 상승한다."""
    if lift_mm > 0.0:
        movel([0.0, 0.0, lift_mm, 0.0, 0.0, 0.0], vel=PROBE_VEL, acc=PROBE_ACC, mod=DR_MV_MOD_REL)
    draw_z = float(get_current_posx(DR_BASE)[0][2])
    node.get_logger().info(
        f"[2단계 완료] 막대기 접촉 높이에서 +{lift_mm:.2f} mm 상승 -> 붓펜 그리기 Z={draw_z:.2f} mm"
    )
    return draw_z


def build_test_path(shape: str, length_mm: float) -> list[tuple[float, float]]:
    """테스트 그리기용 변 단위 이동 경로[(dx, dy), ...]를 생성한다."""
    if shape == "square":
        return [(length_mm, 0.0), (0.0, length_mm), (-length_mm, 0.0), (0.0, -length_mm)]
    return [(length_mm, 0.0)]


def draw_smooth_test() -> None:
    """맞춰진 높이에서 붓펜으로 끊김 없이 스무스하게 테스트 경로를 그린다."""
    moves = build_test_path(DRAW_SHAPE, TEST_DRAW_LENGTH_MM)
    time.sleep(SETTLE_TIME_S)
    draw_baseline = read_fz_avg()
    node.get_logger().info(
        f"[3단계] 붓펜 스무스 그리기 시작 (형태={DRAW_SHAPE}, 길이={TEST_DRAW_LENGTH_MM} mm, 기준 Fz={draw_baseline:.3f} N)"
    )

    for idx, (dx, dy) in enumerate(moves, start=1):
        movel([dx, dy, 0.0, 0.0, 0.0, 0.0], vel=DRAW_VEL, acc=DRAW_ACC, mod=DR_MV_MOD_REL)
        delta_after = CONTACT_SIGN * (read_fz() - draw_baseline)
        node.get_logger().info(
            f"그리기 구간 {idx}/{len(moves)} 완료 | deltaFz={delta_after:+.3f} N"
        )
        if delta_after >= HARD_LIMIT_FORCE_N:
            raise RuntimeError(f"그리기 중 과압 감지(deltaFz={delta_after:+.3f} N). 작업 중단")

    node.get_logger().info("[3단계 완료] 붓펜 스무스 그리기 완료")


def main() -> None:
    with RunLogSession("draw1"):
        try:
            if not (0.0 < CONTACT_FORCE_DELTA_N < HARD_LIMIT_FORCE_N):
                raise ValueError("CONTACT_FORCE_DELTA_N은 0보다 크고 HARD_LIMIT_FORCE_N보다 작아야 합니다.")
            if not (0.0 < PROBE_STEP_MM <= PROBE_MAX_TRAVEL_MM):
                raise ValueError("PROBE_STEP_MM과 PROBE_MAX_TRAVEL_MM 설정을 확인하세요.")
            if LIFT_AFTER_STICK_MM < 0.0:
                raise ValueError("LIFT_AFTER_STICK_MM은 0 이상이어야 합니다.")

            set_tool(TOOL_NAME)
            set_tcp(TCP_NAME)

            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
            movel(posx(READY_OFFSET), vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)

            baseline_fz = measure_baseline()
            probe_stick_contact(baseline_fz)
            adjust_height_for_brush(LIFT_AFTER_STICK_MM)

            if ENABLE_DRAWING:
                draw_smooth_test()
            else:
                node.get_logger().info("ENABLE_DRAWING=False: 높이 조절까지만 확인하고 그리기는 생략합니다.")

            movel([0.0, 0.0, END_LIFT_MM, 0.0, 0.0, 0.0], vel=L_VEL, acc=L_ACC, mod=DR_MV_MOD_REL)
            node.get_logger().info(f"테스트 종료: 안전 높이 +{END_LIFT_MM:.1f} mm 상승 완료")

            movej(posj(HOME_JOINTS), vel=J_VEL, acc=J_ACC)
        except Exception as exc:
            node.get_logger().error(f"draw1 중단: {exc}")
            raise
        finally:
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
