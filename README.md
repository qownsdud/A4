# `ws_dsr` — Doosan M0609 + RG2 라인아트 드로잉 ROS2 워크스페이스 (`bae` 브랜치)

두산 협동로봇(M0609)과 OnRobot RG2 그리퍼를 기반으로, 키오스크 입력 → 라인아트 변환 → 벡터 경로 추출 → 로봇 드로잉 제어까지 수행하는 **ROS2 colcon 워크스페이스**입니다.

---

## 1. 폴더 구조 (정리 기준)

협업 시 혼동을 줄이기 위해 빌드 산출물(`build/`, `install/`, `log/`), 캐시(`__pycache__/`), 중첩 `.git`은 제외하고, 백업/유틸리티/소스를 목적별로 분리했습니다.

```text
.
├── .gitignore                         # ROS2 빌드 산출물(build/install/log), 캐시, 민감 파일 제외
├── README.md                          # 워크스페이스 구조, 정리 내역 및 빌드/실행 가이드
│
├── src/                               # ROS2 colcon 워크스페이스 소스 패키지
│   ├── README.md                      # M0609 + RG2 상세 환경 설정 및 패키지 히스토리
│   ├── art/                           # 통합 아트 드로잉 ROS2 패키지 (kiosk, lineart, path_planner, drawing_controller, job_manager)
│   ├── collaborate1/                  # 드로잉 앱·실험·캘리브레이션·필압 테스트 패키지
│   ├── doosan-robot2/                 # 두산 협동로봇 ROS2 드라이버 및 URDF/MoveIt2 패키지
│   ├── onrobot-ros2/                  # OnRobot 그리퍼 ROS2 드라이버
│   ├── rg2/                           # RG2 그리퍼 제어/시뮬레이션 패키지
│   ├── rokey/                         # 초기 로봇 이동 및 MoveIt Python 데모 패키지
│   └── rokey1/                        # 초기 기어 작업/이동 테스트 패키지
│
├── archive/                           # 초기 백업 및 단독 실험 스크립트 (ROS2 빌드 대상에서 분리)
│   ├── collaborate1_backup/           # (구 src/collaborate1_codeback) 초기 실험 백업 스크립트
│   └── doosan_test/
│       └── drawingtest1.py            # (구 src/doosan-robot2/test/drawingtest1.py) 초기 이동 테스트
│
├── tools/                             # 워크스페이스 관리 유틸리티
│   ├── file_manager.py                # files.yaml 기반 파일 트리 조회 및 일괄 이름/경로 관리 도구
│   └── files.yaml                     # 워크스페이스 파일 트리 정의 매니페스트
│
├── drawing_previews/                  # 벡터 경로 변환 미리보기 이미지 (latest_preview.png 및 history/)
├── run_logs/                          # 실행 로그 텍스트 파일
└── calibration_backup/                # ~/.ros/ 캘리브레이션 및 슬롯 티칭 JSON 백업
    ├── draw_height_test_state.json
    ├── pen_slots.json
    ├── plane_calibration.json
    └── stick_slot.json
```

---

## 2. 주요 정리 및 파일명 정정 내역

| 구분 | 변경 전 | 변경 후 | 사유 |
| :--- | :--- | :--- | :--- |
| 파일명 오타 수정 | `src/collaborate1/collaborate1/experiments/grip_text.py` | `src/collaborate1/collaborate1/experiments/grip_test.py` | 오타(`text` → `test`) 정정 및 `config/registry.yaml`, `src/README.md` 참조 동기화 |
| 백업 폴더 분리 | `src/collaborate1_codeback/` | `archive/collaborate1_backup/` | 활성 ROS2 패키지(`src/collaborate1/`)와의 혼동 방지 |
| 단독 테스트 분리 | `src/doosan-robot2/test/drawingtest1.py` | `archive/doosan_test/drawingtest1.py` | 외부 베이스 패키지(`doosan-robot2`) 내부의 임의 테스트 파일 분리 |
| 유틸리티 정리 | `./file_manager.py`, `./files.yaml` | `tools/file_manager.py`, `tools/files.yaml` | 루트 디렉터리 가독성 개선 |
| 중첩 Git 제거 | `src/.git/` | 제거 | 서브모듈(gitlink)로 묶여 파일이 누락되는 문제 방지 |

---

## 3. 빌드 및 실행 방법 (ROS2 Jazzy)

상세 의존성 설치 및 DRCF 에뮬레이터 설정은 [`src/README.md`](./src/README.md)를 참고하세요.

```bash
# 워크스페이스 루트에서 의존성 설치 및 빌드
rosdep install -r --from-paths src --ignore-src --rosdistro $ROS_DISTRO -y
colcon build
source install/setup.bash

# 통합 아트 드로잉 시스템 실행
ros2 launch art art_system.launch.py
```
