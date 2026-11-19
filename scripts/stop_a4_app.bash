#!/usr/bin/env bash
# 백그라운드에 남은 A4 Drawing Studio 및 sodreal 프로세스를 안전하게 정리합니다.
set -uo pipefail
pkill -INT -f "ros2 launch art_bringup art_system.launch.py" 2>/dev/null || true
pkill -INT -f "ros2 launch m0609_rg2_bringup bringup.launch.py" 2>/dev/null || true
pkill -INT -f "/install/art_" 2>/dev/null || true
sleep 1.0
pkill -TERM -f "/install/art_" 2>/dev/null || true
echo "A4 Drawing Studio 관련 프로세스를 정리했습니다."
