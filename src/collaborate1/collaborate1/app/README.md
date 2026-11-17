# 한글 캘리그라피 로봇 드로잉 (`app`)

Doosan M0609 + RG2 그리퍼 환경에서 한글/영문/숫자 캘리그라피 폰트의 중심선과 획 굵기를 추출해, Z축 필압 조절로 붓글씨를 그리는 실험 코드입니다.

---

## 1. 파일 구성

* **`calligraphy_path_gen.py`**: `.ttf` / `.otf` / `.ttc` 폰트에서 글자의 중심선(Skeleton)과 각 지점의 획 반지름(Distance Transform)을 추출해 로봇용 상대 좌표 `(x_mm, y_mm, dz_mm)` 경로로 변환하고 미리보기 이미지(`preview.png`)를 생성합니다.
* **`draw_calligraphy.py`**: 실제 로봇을 구동해 아래 순서로 작업을 수행합니다.
  1. 실행 즉시 미리보기 이미지(`run_logs/preview_<문구>_<YYYYMMDD_HHMMSS>.png`) 자동 저장 및 `xdg-open`으로 자동 열기
  2. 홈 위치 이동 (`HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]`)
  3. 기준 막대(`~/.ros/stick_slot.json`) 픽업 → `Fz` 센서로 바닥 접촉 높이(`contact_z`) 탐색 → 기준 막대 반납
  4. 1번 펜(`~/.ros/pen_slots.json` 첫 번째 슬롯) 픽업
  5. **굵기 없는 버전** 먼저 그리기 (고정 Z 오프셋 `PEN1_BASE_Z_OFFSET = 13.5mm`)
  6. Y축 아래로 `--gap-mm`(기본 `20.0mm`) 간격을 띄워 **굵기 있는 버전** 그리기 (`THICK_DELTA_MM = -0.5mm` ~ `THIN_DELTA_MM = +0.5mm`)
  7. 안전 상승 → 1번 펜 원위치 반납 → 홈 위치 복귀

---

## 2. 사전 준비 (패키지 & 폰트 설치)

```bash
sudo apt update && sudo apt install -y \
  python3-pil python3-numpy python3-skimage python3-scipy fonts-nanum-extra
```

* 설치 확인:
  ```bash
  python3 -c "import PIL, numpy, skimage, scipy; print('OK')"
  ```
* 기본 붓글씨 폰트 경로: `/usr/share/fonts/truetype/nanum/NanumBrush.ttf`
  *(해당 경로에 폰트가 없을 경우 시스템 기본 `NotoSerifCJK-Bold.ttc`로 자동 대체됩니다.)*

---

## 3. 사용 방법

### ① 경로 미리보기 이미지 확인 (로봇 미동작)
`~/ws_cobot_pjt/ws_dsr`에서 실행:
```bash
python3 src/collaborate1/collaborate1/app/calligraphy_path_gen.py \
  --text "한글" \
  --font /usr/share/fonts/truetype/nanum/NanumBrush.ttf \
  --preview preview.png

xdg-open preview.png
```
* 회색 폰트 위에 **빨간 선(추출된 중심선)**과 **파란 점(각 획 시작점)**이 표시됩니다.

### ② 실제 로봇으로 캘리그라피 그리기 (미리보기 자동 저장 & 열기 포함)
> **주의**: 실행 전 티치 펜던트(또는 제어기)가 **수동(Manual) 모드**인지 확인하세요. (자동 모드에서는 `set_tool` 호출 시 타임아웃이 발생합니다.)

`~/ws_cobot_pjt/ws_dsr`에서 실행:
```bash
source install/setup.bash
python3 src/collaborate1/collaborate1/app/draw_calligraphy.py --text "한글"
```
* 실행 시 `run_logs/preview_<문구>_<YYYYMMDD_HHMMSS>.png`가 자동 저장되고 이미지 뷰어가 함께 열립니다.

---

## 4. 주요 옵션 및 튜닝 파라미터

| 옵션 / 상수 | 기본값 | 설명 |
| --- | --- | --- |
| `--text` | `"한글"` | 그릴 문구 (한글, 영어, 숫자 등 폰트 지원 문자 모두 가능) |
| `--font` | `NanumBrush.ttf` | 사용할 `.ttf` / `.otf` / `.ttc` 폰트 경로 |
| `--width-mm` | `60.0` | 전체 문구 가로 폭 (mm). 문구가 길면 값을 키우세요. |
| `--pen-z-offset` | `13.5` | 기준 막대 접촉 높이 대비 1번 펜 기본 Z 오프셋 (mm) |
| `--gap-mm` | `20.0` | 굵기 없는 버전과 있는 버전 사이의 Y축 간격 (mm) |
| `THICK_DELTA_MM` | `-0.5` | `draw_calligraphy.py` 내부 상수. 더 굵게 누르려면 음수를 크게 설정 |
| `THIN_DELTA_MM` | `+0.5` | `draw_calligraphy.py` 내부 상수. 더 얇게 스치려면 양수를 크게 설정 |

---

## 5. 참고 사항 (로그 경고)
* 실행 중 `dsr_hw_interface2` 또는 `controller_manager`에서 `Skip dt=...`, `Overrun detected!` 경고가 뜰 수 있습니다. 이는 일반 리눅스 커널에서 GUI/화면 녹화 등과 함께 100Hz 제어 루프를 돌릴 때 발생하는 타이밍 경고(`[WARN]`)로, 로봇이 멈추지 않는 한 정상 동작 범위입니다.
