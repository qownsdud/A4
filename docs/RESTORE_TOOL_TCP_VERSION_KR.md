> 복원 이후 추가 수정이 적용됐습니다. `RESTORE_FILES_SHA256.json`은 복원 시점 기록으로 보존하며 현재 파일 해시가 아닙니다. 최신 변경은 [중단점 복구와 새 그림 시작](CHECKPOINT_RECOVERY_KR.md)을 확인하세요.

# Tool/TCP 수정 직후 코드 복원 기록

## 복원 대상

2026년 11월 18일 14시 25~26분경, 전체 Launch의 Tool/TCP 기본값을 `Tool_Weight` / `GripperDA_v1`로 지정한 직후의 로컬 코드를 재구성했다. 이후 논의한 별도 `art_drawing_controller` 패키지로의 새 통합은 반영하지 않았다.

현재 위치는 `/home/yongsoo/A4`이다. 복원 대상 시점에는 JobManager와 SQLite가 없는 다음 5개 패키지를 사용했다.

- `art_interfaces`: ROS 서비스·액션·상태 계약.
- `art_kiosk`: 통합 UI, 사진·문구 입력, 미리보기와 제어 요청.
- `art_kiosk_bridge`: HTTP와 ROS 통신 연결.
- `art_artwork_pipeline`: 선화·계획 생성과 당시의 독립 드로잉 실행기.
- `art_bringup`: 전체 Launch와 Tool/TCP 기본값 전달.

## 복원 근거와 한계

해당 시점의 Git 커밋이나 전체 파일 스냅샷은 없었다. 남아 있는 `A4 (Copy)` 백업과 이 대화의 실제 파일 수정 명령을 바탕으로 복원했다. 따라서 모든 파일이 당시와 바이트 단위로 동일하다고 보장하지 않는다.

백업에서 누락된 최초 드로잉 원본은 저장소의 원본 파일을 읽기 전용으로 확보했다. 원본 Git blob은 `5f25fe47a57b85071ee4b5bcfc48cd2feda65452`이다. 대화에 남은 당시 원본 출력의 583줄과 별도 46줄 구간을 대조해 당시 실행기 기준을 재구성한 뒤, 기록된 수정 내용을 재적용했다. GitHub에는 쓰지 않았다.

기록의 네트워크·로봇 시험 명령은 복원 과정에서 다시 실행하지 않았다. 원래 실패했던 잘못된 작업 경로의 명령과 빌드 캐시 정리도 코드 복원 근거에서 구분했다. 적용 기록은 루트의 `RESTORE_REPLAY.json`, 현재 코드 파일의 SHA-256 목록은 `RESTORE_FILES_SHA256.json`에 있다.

## 시험 파일 보존

당시 마지막 성공 실행의 pytest 목록 129개를 보관된 기록에서 확인했다. 현재 활동 시험을 그 목록과 대조했다. 백업에만 남아 있던 다른 버전의 시험은 `reference_tests_from_backup/`에 보관했으며 현재 통과 수에 포함하지 않았다. `A4 (Copy)` 원본은 수정하지 않았다.

## 이번 실제 검증

다음 명령을 복원된 A4에서 실행했다. 시험용 ROS 도메인 99를 사용했으며 실제 로봇을 움직이지 않았다.

```bash
cd ~/A4
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/local_setup.bash
source ros2_ws/install/local_setup.bash
source scripts/local_test_env.bash
PYTHONPATH="/tmp/a4-hmi-js-check:$PYTHONPATH" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 -m pytest -c /dev/null --rootdir=. \
  -o cache_dir=/tmp/a4-restored-pytest-cache tests -q -rs
```

- 결과: 129개 통과, 실패 0, 건너뜀 0.
- 로그: `/tmp/a4-restored-tests.log`.
- 시험 목록 대조: `/tmp/a4-restored-collected.txt`.
- ROS2 전체 빌드 로그: `/tmp/a4-restored-final-build.log`.
- Python 구문 검사와 Launch의 `--show-args` 확인을 수행했다. Launch 인자 조회는 노드를 실행하지 않는다.

현재 PC의 이전 overlay 경로에 대한 경고를 피하기 위해 검증 명령에서는 각 설치의 `local_setup.bash`를 읽었다.

## 보존한 것과 미복원 데이터

사용자 홈의 기존 보정 JSON, 펜 슬롯, 기준 막대, 장비 보호 설정은 변경하지 않았다. GitHub, 로봇 제어기, Tool/TCP의 실제 선택값도 변경하지 않았다.

삭제된 이전 A4 폴더의 작업 사진·도안·실행 이력 전체를 되살린 것은 아니다. 코드 복원으로 과거 작업이 실제 종료되었다고 기록하거나 새로운 작업을 자동 실행하지 않았다. 기존 백업의 데이터도 삭제하지 않았다.

## 실물 실행 상태

이 복원은 예상 밖 이동의 원인을 수정한 작업이 아니다. 당시 좌표 변환과 모션 코드를 복원한 것이다. 실제 로봇에서 다시 사용하기 전에 종이 좌표, Tool/TCP, 슬롯 위치와 예상 이동 경로를 별도로 검증해야 한다. 소프트웨어 시험 통과는 물리 이동 검증을 뜻하지 않는다. 이번 작업에서 실물 이동은 실행하지 않았다.
