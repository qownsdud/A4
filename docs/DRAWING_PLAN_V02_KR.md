# DrawingPlan v0.2 — Phase 3 ↔ JobManager 공동 계약

적용 범위: **종이 위 2차원 경로 데이터**, ROS 2 JobManager의 작업 등록 및 가상 컨트롤러 시험.
**실제 M0609 로봇의 동작 좌표/안전 승인을 뜻하지 않는다.**

## 1. 설계 결정

- 기존 JobManager v0.1의 `job_id`, `paper_mm`, `strokes`, **1부터 연속된 정수 `stroke_id`**, 획 순서 및 SHA-256 파일 불변성은 유지한다.
- Phase 3의 `unit`, `coordinate_frame`, `seed`, `grid`, `optimization` 메타데이터를 가져온다.
- `schema_version`은 문자열 `"0.2"`다. 펜 ID는 `PEN_1`, `PEN_2`, `PEN_3`로 통일한다.
- `coordinate_frame`은 **`paper_top_left_x_right_y_down`**: A4 가로(297×210mm) 또는 세로(210×297mm), 종이 왼쪽 위 원점, X 오른쪽, Y 아래쪽. 이미지와 같은 방향으로 저장하므로 Phase 3 단계에서 Y 반전하지 않는다.
- 과거 `TEAM_CONTRACT_V1.md`의 왼쪽 아래 원점 제안은 **v0.1 단계의 미확정 제안**이었다. v0.2에서는 위 원점을 **파일 계약**으로 정하되, 실물 로봇 좌표계/로봇 베이스 변환은 **팀 검토 및 별도 안전 승인 전까지 미확정**이다.
- JobManager는 과거 시험 파일을 유지하기 위해 v0.1도 읽지만, **Phase 3의 새로운 출력은 v0.2만 생성**한다.

## 2. JSON 예시

```json
{
  "schema_version": "0.2",
  "job_id": "JOB_V02_001",
  "unit": "mm",
  "coordinate_frame": "paper_top_left_x_right_y_down",
  "paper_mm": {"width": 210.0, "height": 297.0},
  "seed": 42,
  "grid": {"type": "4x4", "cell_pen_ids": ["PEN_1", "PEN_2", "PEN_3", "PEN_1", "PEN_2", "PEN_3", "PEN_1", "PEN_2", "PEN_3", "PEN_1", "PEN_2", "PEN_3", "PEN_1", "PEN_2", "PEN_3", "PEN_1"]},
  "strokes": [
    {
      "stroke_id": 1,
      "execution_order": 0,
      "pen_id": "PEN_1",
      "grid_id": 0,
      "layer": "artwork",
      "points_mm": [[10.0, 10.0], [20.0, 20.0]]
    }
  ]
}
```

`grid`, `seed`, `optimization`은 별도의 이미지 처리 메타데이터로 취급한다. JobManager는 단지 계약 형식과 유효성을 검사하고 로봇 동작 명령으로 사용하지 않는다. `grid_id`가 있다면 해당 `grid.cell_pen_ids` 항목과 `pen_id`가 같아야 한다. `execution_order`가 있다면 0부터 순서대로 증가해야 한다. 좌표는 모두 `[0,paper_mm.width] × [0,paper_mm.height]` 범위의 유한한 숫자, 획당 점 최소 2개여야 한다.

## 3. 실제 작업 파일 저장

최종 등록 파일은 반드시 다음 경로에 **불변(덮어쓰기 금지)** 으로 저장한다.

```
$ART_JOB_PLAN_ROOT/<job_id>/drawing_plan.json
```

- `job_id`는 `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$` 규칙을 따른다.
- Phase 3 `write_job_plan()`은 임시 파일을 완성한 후 동일 파일시스템에서 원자적으로 공개하며 기존 파일이 있으면 오류를 낸다.
- JobManager는 경로, JSON 크기 5MB 제한, `job_id`, schema, paper/mm, 좌표, 획 ID, 펜, SHA-256을 검사한다.
- 파일이 이미 있으면 **새 Job ID를 발급**한다. 동일 작업 ID로 기존 파일을 수정하지 않는다.

## 4. Ubuntu에서 검증하는 순서

아래 명령은 A4 프로젝트 루트 `~/A4`에서 실행한다. Phase 3 전용 `.venv`가 설치되어 있어야 한다.

### A. 사진(라인아트)에서 v0.2 원본 생성

```bash
cd ~/A4
source ros2_ws/install/setup.bash
python3 -m art_artwork_pipeline.path_planner.cli \
  --input data/reference/kiosk/confirmed_outputs/latest_lineart.png \
  --out-dir data/reference/path_planner/outputs/v02_check \
  --job-id JOB_V02_101 --seed 42
```

`main.py`의 `*_drawing_plan.json`은 v0.2 파일이다. SVG 미리보기도 함께 생성된다. 이 단계에서는 작업별 JobManager 파일을 발행하지 않는다.

### B. 최적화 후 JobManager용 불변 파일로 공개

```bash
export ART_JOB_PLAN_ROOT="$HOME/A4/examples/job_manager"
python3 -m art_artwork_pipeline.path_planner.optimize_existing \
  --input data/reference/path_planner/outputs/v02_check/latest_lineart_drawing_plan.json \
  --output data/reference/path_planner/outputs/v02_check/latest_lineart_drawing_plan_optimized.json \
  --strokes 48 --backend opencv \
  --plan-root "$ART_JOB_PLAN_ROOT"
```

등록 경로는 `~/A4/examples/job_manager/JOB_V02_101/drawing_plan.json`이다. `--strokes 48`은 중요한 선을 **제외**할 수 있으므로 반드시 SVG/미리보기를 검토한다. 무손실 보장이 필요하다면 Stroke 제한을 적용하지 않는 별도 전략이 필요하다.

> 최적화 **없이** 바로 JobManager 계획을 발행할 때는 A 단계 `main.py`에 `--plan-root "$ART_JOB_PLAN_ROOT"`를 추가하면 된다. 한 번 발행한 파일은 최적화 결과로 덮어쓰지 않는다.

### C. 계약 테스트

```bash
cd ~/A4
source ros2_ws/install/setup.bash
python -m pip install pytest
PYTHONPATH=ros2_ws/src/art_job_manager \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -c /dev/null tests/artwork_pipeline -q
```

패치 포함 테스트는 총 14개다. 기존 프로젝트 테스트는 ROS, QuickJS, 실서버 선택 테스트가 환경에 따라 건너뛸 수 있다.

### D. JobManager에서 파일 확인 (ROS 불필요)

```bash
PYTHONPATH=ros2_ws/src/art_job_manager python - <<'PY'
import os
from pathlib import Path
from art_job_manager.plan import load_plan
root=Path(os.environ['ART_JOB_PLAN_ROOT']).expanduser()
p=root/'JOB_V02_101'/'drawing_plan.json'
s=load_plan('JOB_V02_101', str(p.resolve()), plan_root=root)
print('검증 성공:', s.stroke_count, '획 / SHA-256:', s.sha256)
PY
```

이후 기존 관리자 HMI에 Job ID와 완성된 계획 파일 절대경로를 등록해서 **Fake Controller** 시험을 진행한다.

## 5. 로봇 연동의 안전 경계

- v0.2 좌표는 `paper_top_left_x_right_y_down` 2D **종이 좌표**이다. 실제 M0609 로봇 좌표가 아니다.
- 실제 컨트롤러는 종이 프레임→robot base의 정밀 캘리브레이션, PEN_1/2/3 실물 펜 매핑, 펜끝 TCP, 작업면 Z, pen-up/down, 속도/가속도, 충돌 및 작업영역 검사를 별도로 구현해야 한다.
- 컨트롤러가 v0.2를 인식하지 않거나 캘리브레이션이 확정되지 않았다면 **Goal을 거부**해야 한다.
- ROS Bridge/HMI의 PAUSE, CANCEL은 물리적 비상정지 기능이 아니다. Fake Controller의 물리 정지 확인 메시지는 시뮬레이션일 뿐이다.
