#!/usr/bin/env python3
"""Read-only Fz logging while the Doosan teach pendant owns robot control.

This program NEVER commands robot motion, stop, compliance, gripper, or mode.
Start with the brush pen clear of the paper and the robot stationary.
Whether external read-only requests work with pendant control is driver-dependent.
"""
import csv
import math
import statistics
import time
from pathlib import Path

import rclpy
import DR_init

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
SETTLE_SEC = 3.0
BASELINE_SEC = 5.0
MONITOR_SEC = 30.0
SAMPLE_SEC = 0.2
CSV_FILE = Path.home() / "pendant_force_monitor.csv"


def main():
    DR_init.__dsr__id = ROBOT_ID
    DR_init.__dsr__model = ROBOT_MODEL
    rclpy.init(args=None)
    node = None
    rows = []
    try:
        node = rclpy.create_node("pendant_force_monitor", namespace=ROBOT_ID)
        DR_init.__dsr__node = node
        from DSR_ROBOT2 import DR_BASE, get_tool_force
        log = node.get_logger()
        log.info("Fz 읽기 전용: 이동/정지/로봇 모드 변경 명령 없음")
        log.info("티치펜던트로 제어권을 가져온 상태에서 붓펜을 종이와 떨어뜨려 정지시키세요.")
        log.info("먼저 3초 안정화 + 5초 비접촉 기준값 측정. 이후 30초 동안 값 관찰")
        time.sleep(SETTLE_SEC)
        baseline = []
        start = time.monotonic()
        total_n = round((BASELINE_SEC + MONITOR_SEC) / SAMPLE_SEC)
        baseline_n = round(BASELINE_SEC / SAMPLE_SEC)
        ref = None
        next_read = time.monotonic()
        for i in range(total_n):
            delay = next_read - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            t = time.monotonic() - start
            try:
                fz = float(get_tool_force(DR_BASE)[2])
            except Exception as exc:
                raise RuntimeError(
                    "Fz 읽기 실패: 티치펜던트 제어권에서 ROS2 읽기 요청이 허용되지 않거나 "
                    "드라이버/연결 상태가 잘못되었을 수 있습니다"
                ) from exc
            if not math.isfinite(fz):
                raise RuntimeError(f"센서 비정상 값: {fz}")
            if i < baseline_n:
                phase = "baseline"
                baseline.append(fz)
                log.info(f"[비접촉 {i+1:02d}/{baseline_n}] Fz={fz:+.3f} N")
                if i == baseline_n - 1:
                    ref = statistics.mean(baseline)
                    noise = max(baseline) - min(baseline)
                    log.info(f"비접촉 기준 Fz={ref:+.3f} N, 범위={noise:.3f} N")
                    log.info("이제 관찰 시작. 수동 조작은 티치펜던트에서만 수행하세요.")
            else:
                phase = "observe"
                delta = fz - ref
                log.info(f"[관찰 {t-BASELINE_SEC:5.1f}s] Fz={fz:+.3f} N  ΔFz={delta:+.3f} N")
            rows.append((f"{t:.3f}", phase, f"{fz:.4f}", "" if ref is None else f"{fz-ref:+.4f}"))
            next_read += SAMPLE_SEC
        log.info("측정 종료. 외력 변화만으로 최초 접촉이나 안전 필압을 확정할 수 없습니다.")
    except KeyboardInterrupt:
        if node:
            node.get_logger().warn("센서 기록 중단. 이 프로그램은 로봇을 정지시키지 않습니다.")
    except Exception as exc:
        if node:
            node.get_logger().error(str(exc))
        raise
    finally:
        if rows:
            try:
                with CSV_FILE.open("w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["elapsed_s", "phase", "fz_N", "delta_fz_N"])
                    writer.writerows(rows)
                if node:
                    node.get_logger().info(f"CSV 저장: {CSV_FILE}")
            except OSError as exc:
                if node:
                    node.get_logger().error(f"CSV 저장 실패: {exc}")
        if node:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
