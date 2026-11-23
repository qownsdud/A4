# A4 드로잉 파이프라인 알고리즘 테스트 및 적용 정리

이 문서는 현재 브랜치(`jang` / `main`)의 `art_artwork_pipeline` 실제 코드로 동일한 입력 사진(`00_input_photo.png`)을 단계별로 실행해 생성한 발표용 샘플과 알고리즘 정리 문서입니다.

---

## 폴더 구성

- `README.md` — 단계별 테스트 흐름, 현재 브랜치 적용 내용 및 생성 결과 정리
- `00_input_photo.png` — 공통 입력 사진
- `01_lineart_compare.png` — 1단계 선화 추출 비교 (Baseline vs Face ROI vs Face ROI + GrabCut)
- `02_line_merge_compare.png` — 2단계 짧은 선 연결(`bridge_gap_px`) 비교 (`0.0` vs `4.0` vs `12.0` px)
- `03_length_epsilon_compare.png` — 3단계 길이 필터링(`min_length_px`) 및 단순화(`epsilon`) 비교
- `04_pen_assignment.png` — 4단계 3색 펜(`PEN_1`, `PEN_2`, `PEN_3`) 균형 배정 결과
- `05_final_lineart.png` — 5단계 통합 파이프라인(`prepare_artwork`) 선화 결과
- `06_final_preview.svg` — 5단계 통합 파이프라인 최종 미리보기 SVG (`Hello World` 포함)
- `07_final_preview.png` — 5단계 통합 파이프라인 최종 미리보기 PNG (총 `66`획)

---

## 0단계. 공통 입력 사진

- 입력 이미지: ![00_input_photo.png](./00_input_photo.png)

---

## 1단계. 선화 추출 및 디테일 보정 (`lineart_cv.py`)

### 테스트 및 비교 내용

동일 입력 사진(`detail='medium'`, `max_side=512`, `binarize=True`, `paper='a4'`)에 대해 세 가지 구성을 비교했습니다.

- **1) Baseline Canny** (`use_face_roi=False`, `use_person_segmentation=False`): 추출 획 `53`개. 얼굴 이목구비(입·코 등) 디테일이 일부 누락되고 배경 창문·책상 선이 그대로 남습니다.
- **2) + Face ROI** (`use_face_roi=True`, `use_person_segmentation=False`): 추출 획 `56`개. Haar 얼굴 검출 기반 타원 마스크 내부에 2단계 `bilateralFilter`와 낮은 Canny 임계값을 적용해 눈·코·입 윤곽을 살렸습니다.
- **3) + Face ROI & GrabCut (현재 적용)**: 추출 획 `33`개. 얼굴 위치 기반 `cv2.grabCut`으로 인물 전경을 분리하고, 배경은 `GaussianBlur` + 상향된 Canny 임계값 + `connectedComponentsWithStats`(`area >= 28` 또는 `max(bw, bh) >= 26`)로 큰 윤곽선만 남겨 배경 잡음을 줄였습니다.

### 현재 브랜치 적용 내용

- `LineartConverterCV`에 `use_face_roi=True`와 `use_person_segmentation=True`가 기본 활성화되어 있습니다.
- `resolve_cv_density_params`로 외부 디테일 슬라이더(`0~100`)를 유효 구간(`20~80`)에 매핑해 `DENSITY_ANCHORS` 5단계(`Minimal`~`Very Rich`) 사이에서 Canny 임계값과 `min_length_px`를 선형 보간합니다.

### 샘플 파일

- ![01_lineart_compare.png](./01_lineart_compare.png)

---

## 2단계. 끊어진 짧은 선 연결(병합) (`extractor.py`)

### 테스트 및 비교 내용

1단계 최종 선화(`+ Face ROI & GrabCut`)를 기준으로 `_bridge_close_strokes`의 `bridge_gap_px` 값을 바꿔 비교했습니다.

- **1) 병합 없음 (`bridge_gap_px=0.0`)**: `63`획. 짧은 선 조각이 많이 남아 펜 업/다운 횟수가 늘어납니다.
- **2) 현재 적용 (`bridge_gap_px=4.0`)**: `33`획. 가까운 끊김만 자연스럽게 이어 획 수를 약 절반으로 줄였습니다.
- **3) 과도한 병합 (`bridge_gap_px=12.0`)**: `19`획. 획 수는 더 줄지만 서로 다른 윤곽선이 이어질 위험이 커집니다.

### 현재 브랜치 적용 내용

- 벡터 추출 단계(`pipeline_runner.py` → `extract_vector_paths`)에서는 거리 기반 탐욕 병합 `bridge_gap_px=4.0`을 적용합니다.
- 이후 `optimize_plan` 단계에서도 동일 펜 레이어 내 `merge_tolerance_mm=0.35` 병합(`_merge_same_pen`)과 최근접 이웃 정렬(`_sort_same_pen`)을 추가로 수행합니다.

### 샘플 파일

- ![02_line_merge_compare.png](./02_line_merge_compare.png)

---

## 3단계. 길이 필터링 및 점 개수 조절 (`extractor.py`)

### 테스트 및 비교 내용

`bridge_gap_px=4.0` 조건에서 `min_length_px`와 `cv2.approxPolyDP` `epsilon` 조합 3가지를 비교했습니다.

- **1) High Detail (`min_length_px=5.2`, `epsilon=0.5`)**: `44`획 / `2,058`점. 세밀하지만 로봇 제어용 점 개수가 많습니다.
- **2) Balanced (현재 적용, `min_length_px=7.0`, `epsilon=0.9`)**: `33`획 / `594`점. 형태를 유지하면서도 점 개수를 크게 줄였습니다.
- **3) Light (`min_length_px=15.0`, `epsilon=1.8`)**: `28`획 / `225`점. 점은 가장 적지만 곡선이 각지고 짧은 디테일이 탈락합니다.

### 현재 브랜치 적용 내용

- `pipeline_runner.py`에서는 `epsilon=0.9`로 고정하고, `min_length_px`는 디테일 슬라이더(`4.0~16.0` 범위 내 `20~80` 매핑, `medium` 기준 `7.0`)에 따라 동적으로 조절합니다.
- 앞단 픽셀 단순화 결과를 유지하기 위해 `optimize_plan` 호출 시 `simplify_tolerance_mm=0.0`으로 재단순화를 비활성화했습니다.

### 샘플 파일

- ![03_length_epsilon_compare.png](./03_length_epsilon_compare.png)

---

## 4단계. 3색 펜 색 배정 방식 (`puzzle/colors.py`, `drawing_plan.py`)

### 현재 브랜치 적용 내용

추출된 벡터 획을 `PEN_1`, `PEN_2`, `PEN_3` 3가지 펜에 고르게 나누기 위해 **장획 분할 + 획 단위 균형 배정** 알고리즘을 적용했습니다.

- **1. 긴 획 분할 (`split_long_stroke`)**: `max_stroke_mm=55.0` 기준으로 `55.0 * 1.1`mm를 초과하는 긴 획을 약 `55.0`mm 단위 구간으로 균등 분할하고, 인접한 분할 구간 쌍을 `connected_pairs`로 기록합니다.
- **2. 긴 획 우선 균형 배정 (`assign_stroke_pens`)**: 길이가 긴 획부터 아래 우선순위로 펜을 배정합니다.
  - 1순위: `connected_pairs`로 직접 이어진 인접 분할 구간과 같은 펜 회피
  - 2순위: 공간상(중점 기준) 가장 가까운 기존 획과 같은 펜 회피
  - 3순위: 현재까지 펜별 누적 그리기 길이(`pen_totals`)가 가장 적은 펜 우선
  - 4순위: 최근접 이웃 `neighbor_k=3`개 안에서 가장 적게 등장한 펜 우선
- **3. 격자 매핑 및 실행 정렬 (`build_plan`)**: 각 획 시작점 기준으로 `4×4` 논리 격자(`balanced_cells`, `6:5:5` 비율) 중 동일 펜을 가진 가장 가까운 셀을 `grid_id`로 연결하고, `PEN_1` → `PEN_2` → `PEN_3` 순으로 그룹 정렬합니다.

### 실제 배정 결과 (총 `52`획)

- `PEN_1` (파랑): `17`획 / 총 길이 `580.6`mm
- `PEN_2` (빨강): `17`획 / 총 길이 `582.6`mm
- `PEN_3` (초록): `18`획 / 총 길이 `575.0`mm

### 샘플 파일

- ![04_pen_assignment.png](./04_pen_assignment.png)

---

## 5단계. 전체 파이프라인 통합 결과 (`prepare_artwork`)

### 통합 실행 요약

`pipeline_runner.py`의 `prepare_artwork`를 `method='cv'`, `paper='a4'`, `detail='medium'`, `seed=42`, `text='Hello World'`로 끝까지 실행한 실제 결과입니다.

- 그림 영역(`PEN_1`~`PEN_3`)과 하단 캘리그래피(`PEN_4`, `Hello World`)가 합쳐져 **총 `66`획**의 실행 계획이 생성되었습니다.

### 샘플 파일

- 추출 선화: ![05_final_lineart.png](./05_final_lineart.png)
- 최종 미리보기 PNG: ![07_final_preview.png](./07_final_preview.png)
- 최종 미리보기 SVG: [06_final_preview.svg](./06_final_preview.svg)
