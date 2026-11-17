# Phase 2: 사진 → 라인드로잉 변환 모듈 (`phase2_lib_lineart`)

사람의 실사 사진을 입력받아 로봇 드로잉(Phase 3 벡터 경로 추출)에 적합한 흑백 라인아트 PNG로 변환합니다.

## 확정 파이프라인 (`mfl_ld` 하이브리드 방식)
- **얼굴·머리카락 영역**: MediaPipe `FaceLandmarker`로 얼굴/머리 ROI를 검출하고, `bilateralFilter` + `Canny(22, 65)` + 2px 선 두께 보정으로 이목구비와 외곽선을 끊김 없이 추출합니다.
- **얼굴 외 영역 (어깨·옷·배경)**: `controlnet_aux.LineartDetector` (`pre_smooth=2`, `line_threshold=200`, `min_line_area=5`, `binarize=True`)로 안정적인 선화를 추출해 합성합니다.
- **폴백**: 얼굴이 검출되지 않으면 자동으로 `LineartDetector` 전체 결과를 반환합니다.

## 파일 구성
- `lineart_mfl_ld.py`: **확정 하이브리드 변환기 (`LineartConverterMflLd`)**
- `lineart_dl.py`: `controlnet_aux.LineartDetector` 래퍼 (`LineartConverterDL`)
- `lineart_cv.py`: OpenCV 경량 스케치 변환기 (`LineartConverterCV` — `dodge`, `canny`, `adaptive`)
- `utils.py`: 이미지 로드/정규화, 이진화, 용지 비율(`a4`, `postcard`, `square`) 패딩
- `main.py`: 통합 CLI 실행 스크립트 (기본값 `--method mfl_ld`)

## 실행 방법
```bash
cd /home/qownsdud/Documents/rokey_collaborate_1/phase2_lib_lineart

# 확정 하이브리드 방식으로 변환 (기본값)
.venv/bin/python main.py --input samples/person1.jpg

# A4 용지 비율 패딩 적용
.venv/bin/python main.py --input samples/person1.jpg --paper a4
```

## Python / ROS2 노드 연동 예시
```python
from lineart_mfl_ld import LineartConverterMflLd, LineartMflLdConfig

converter = LineartConverterMflLd(LineartMflLdConfig(paper="a4"))
# OpenCV 카메라 프레임(BGR numpy array) 또는 이미지 경로 모두 지원
lineart_pil = converter.convert(bgr_frame, bgr_input=True)
```
