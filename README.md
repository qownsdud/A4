# AI 기반 키오스크 실물 라인아트 협동로봇 드로잉 시스템 (`rokey_collaborate_1`)

키오스크(웹캠 촬영 / 이미지 업로드)에서 입력받은 이미지를 흑백 라인아트(선화)로 변환하고, 이를 연속 선(Stroke) 기반 벡터 경로로 추출하여 **두산 협동로봇**이 실제 종이(A4 / 엽서 / 정사각형) 위에 펜으로 그려주는 자동화 드로잉 프로젝트입니다.

---

## 1. 전체 파이프라인 아키텍처

```text
[고객 / 키오스크 UI] (phase1_kiosk)
  │  웹캠 촬영 또는 사진 업로드, 디테일/용지 규격 선택
  ▼
[라인아트 변환] (phase2_lib_lineart)
  │  로컬 딥러닝(LineartDetector) / OpenCV(Canny·Dodge·Adaptive) → 이진화 및 용지 비율 맞춤
  │  확정 이미지 저장 → phase1_kiosk/confirmed_outputs/latest_lineart.png
  ▼
[벡터 경로 추출 및 순서 최적화] (phase3_path_planner)
  │  이진화 → 세선화(1px 중심선) → approxPolyDP 단순화 → Nearest-Neighbor TSP 경로 정렬
  │  출력 → phase3_path_planner/outputs/latest_lineart_strokes_px.json & 비교/벡터 이미지
  ▼
[로봇 드로잉 제어] (Phase 4/5 설계: specification/, DSL기본.txt, manuals/)
     픽셀 → 로봇 작업 좌표(X, Y, Z_draw / Z_up) 변환 → ROS2 / 두산 DSL(move_joint, move_task, moveB)
```

---

## 2. 프로젝트 파일 트리

> `.venv/`, `__pycache__/`, `.env`, `.vscode/`, 레거시/실험 보관 폴더(`X/`)는 `.gitignore`를 통해 제외되어 있습니다.

```text
rokey_collaborate_1/
├── README.md                          # 프로젝트 소개, 파일 트리, 연혁 및 기술 문서
├── .gitignore                         # 보안(.env, *.key) 및 대용량(.venv), 아카이브(X/) 제외 설정
├── DSL기본.txt                        # 두산 협동로봇 DSL 기본 제어 명령어 메모
├── 아이디어.txt                       # 초기 프로젝트 기획 및 요구사항·ROS2 구상 메모
├── 전체_업무_파이프라인.txt           # Phase 1~5 End-to-End 상세 설계 및 안전 기준 문서
├── 실행코드.txt                       # 키오스크 서버 및 벡터 경로 추출 실행 명령어
├── project_self_feedback.jpg          # 프로젝트 자체 피드백/설계 검토 이미지
├── file_manager.py                    # files.yaml 기반 프로젝트 트리 조회 및 일괄 파일명/이동 관리 도구
├── test_file_manager.py               # file_manager.py 단위 테스트
├── files.yaml                         # 프로젝트 파일 트리 정의 및 이름/경로 관리 매니페스트
│
├── manuals/                           # 두산 협동로봇 교육 및 안전 매뉴얼
│   ├── 1_협동로봇_초급교육.pdf
│   ├── 2_협동로봇_중급교육.pdf
│   ├── 3_협동로봇_중급교육.pdf
│   └── 협동로봇_주의사항.pdf
│
├── specification/                     # 단계별 기술 명세서
│   ├── 1_ai_lineart_generation.txt    # Phase 1~2 라인아트 생성 명세
│   ├── 2_vector_path_extraction.txt   # Phase 3 벡터 경로 추출 명세
│   └── 3_ros2_hardware_integration.txt# Phase 4~5 ROS2 및 하드웨어 연동 명세
│
├── phase1_kiosk/                      # [Phase 1] FastAPI 기반 키오스크 웹 서버 & 카메라 UI
│   ├── server.py                      # FastAPI 서버 (이미지 전처리, phase2 호출, 확정 이미지 저장)
│   ├── preprocess.py                  # 입력 사진 정규화 (normalize_photo_bytes)
│   ├── static/                        # 프론트엔드 정적 파일
│   │   ├── index.html                 # 키오스크 UI 마크업
│   │   ├── style.css                  # 키오스크 UI 스타일시트
│   │   └── app.js                     # 웹캠/업로드 제어 및 API 연동 스크립트
│   └── confirmed_outputs/             # 사용자가 확정한 최종 라인아트 저장소
│       ├── latest_lineart.png         # Phase 3 입력으로 사용되는 최신 확정 라인아트
│       └── history/                   # 이전 확정 라인아트 아카이브 (타임스탬프별)
│
├── phase2_lib_lineart/                # [Phase 2] 로컬 딥러닝 & OpenCV 라인아트 변환 모듈
│   ├── README.md                      # Phase 2 모듈 가이드 (mfl_ld 하이브리드 파이프라인)
│   ├── main.py                        # CLI 실행 및 mfl_ld/DL/OpenCV 비교/벤치마크 러너
│   ├── lineart_mfl_ld.py              # MediaPipe Face ROI + Canny & LineartDetector 하이브리드 변환기
│   ├── lineart_dl.py                  # controlnet_aux LineartDetector 기반 선화 추출
│   ├── lineart_cv.py                  # OpenCV 기반 선화 추출 (canny / dodge / adaptive)
│   ├── utils.py                       # 용지 규격 비율(PAPER_RATIOS: A4/엽서/정사각형) 및 유틸리티
│   ├── requirements.txt               # Phase 2 Python 의존성 목록
│   ├── models/                        # MediaPipe 얼굴 랜드마크 모델
│   │   └── face_landmarker.task
│   ├── samples/                       # 테스트용 샘플 입력 이미지
│   │   └── person1.jpg
│   └── outputs/                       # 라인아트 변환 테스트 출력 결과
│       ├── person1_cv_canny.png
│       ├── person1_dl_smooth2_clean.png
│       └── person1_mfl_ld.png
│
└── phase3_path_planner/               # [Phase 3] 벡터 Stroke 추출 및 경로 최적화 모듈
    ├── main.py                        # CLI 엔트리포인트 (latest_lineart.png → 벡터 JSON & 시각화)
    ├── extractor.py                   # 이진화·세선화·approxPolyDP 단순화·TSP 경로 정렬
    ├── visualize.py                   # 원본 vs 벡터 비교 시트 및 순수 벡터 이미지 렌더링
    └── outputs/                       # 최신 벡터 추출 결과 및 히스토리
        ├── latest_lineart_strokes_px.json  # 추출된 Stroke 픽셀 좌표 배열
        ├── latest_lineart_vector.png       # 추출된 벡터 경로 시각화
        ├── latest_lineart_comparison.png   # 입력 선화 vs 벡터 경로 비교 이미지
        └── history/                        # 이전 실행 결과 아카이브
```

---

## 3. 연혁 (Development Chronology)

| 단계 / 시점 | 주요 내용 | 관련 산출물 |
| :--- | :--- | :--- |
| **1. 기획 및 로봇 학습** (2026-11-10 ~ 11-12) | 협동로봇 교육 매뉴얼 학습, 두산 로봇 DSL 명령어 정리, 무인 라인아트 드로잉 아이디어 및 요구사항 구체화 | `manuals/*.pdf`, `DSL기본.txt`, `아이디어.txt`, `specification/` |
| **2. 클라우드 AI / 원터치 프로토타입** (2026-11-13 오전) | 외부 API(Cloudflare Workers AI 등) 기반 라인아트 생성 및 원터치 파이프라인 실험 진행 후, 오프라인/무과금·로컬 안정성 확보를 위해 레거시(`X/`)로 분리 보관 | `X/` (`.gitignore` 제외), `project_self_feedback.jpg` |
| **3. 로컬 라인아트 모듈 구축** (2026-11-13 오후) | GPU/CPU 환경에서 즉시 동작하는 로컬 딥러닝(`LineartDetector`) 및 OpenCV(`Canny`/`Dodge`/`Adaptive`) 선화 변환기와 용지 비율 맞춤 구현 | `phase2_lib_lineart/` |
| **4. 키오스크 UI 및 파일 관리 도구** (2026-11-13 오후) | FastAPI 기반 웹캠/업로드 키오스크 서버 구축 및 `phase2_lib_lineart` 연동, 프로젝트 트리/파일명 관리 유틸리티 작성 | `phase1_kiosk/`, `file_manager.py`, `files.yaml`, `test_file_manager.py` |
| **5. 벡터 경로 추출 및 파이프라인 통합** (2026-11-13 오후) | 래스터 선화를 1px 중심선 기반 Stroke로 변환하고 `approxPolyDP` + TSP 정렬로 Pen-Up 이동을 최소화하는 Phase 3 구축 및 전체 파이프라인 문서화 | `phase3_path_planner/`, `전체_업무_파이프라인.txt`, `실행코드.txt` |
| **6. GitHub `main` 저장소 통합** (2026-11-13 ~ 11-16) | `.gitignore`로 민감 정보(`.env`)·가상환경(`.venv`)·실험 파일(`X/`) 제외 후 `main` 브랜치에 전체 소스 및 문서 업로드 | `.gitignore`, `README.md` |

---

## 4. 사용 기술 (Tech Stack)

### Phase 1 — 키오스크 웹 서버 & UI
* **Backend**: Python, **FastAPI**, Uvicorn
* **Frontend**: HTML5, CSS3, Vanilla JavaScript (WebRTC/카메라 캡처 및 이미지 업로드)
* **Image Processing**: Pillow, OpenCV (`normalize_photo_bytes`)

### Phase 2 — 라인아트(선화) 변환
* **Deep Learning**: PyTorch (`torch`, `torchvision`), Hugging Face `transformers`, **`controlnet-aux`** (`LineartDetector`)
* **Computer Vision**: **OpenCV** (`cv2.bilateralFilter`, `cv2.Canny`, Dodge/Adaptive Threshold), NumPy, Pillow

### Phase 3 — 벡터 경로 추출 & 경로 최적화
* **Vectorization**: 이진화, 세선화(Skeletonization / Thinning), Douglas-Peucker 경로 단순화 (`cv2.approxPolyDP`)
* **Path Optimization**: 최근접 이웃(Nearest-Neighbor) 기반 TSP 휴리스틱 정렬 (공중 이동 최소화)
* **Output & Visualization**: Stroke 좌표 JSON (`latest_lineart_strokes_px.json`), 비교 시트/벡터 이미지 렌더링 (`visualize.py`)

### Phase 4 & 5 — 로봇 제어 & 안전 설계 (문서/명세)
* **Robot & Control**: 두산 협동로봇, DART-Platform **DSL** (`move_joint`, `move_task`, `moveB`, `compliance`, `force`), **ROS2** (`kiosk_ui_node`, `path_planner_node`, `robot_drawer_node` Action Server)
* **Tooling**: YAML 기반 파일 트리 관리 (`file_manager.py`, `files.yaml`)

---

## 5. 실행 방법 (Quick Start)

1. **키오스크 서버 실행**
   ```bash
   ./phase2_lib_lineart/.venv/bin/uvicorn server:app --app-dir ./phase1_kiosk --host 0.0.0.0 --port 8000
   ```
2. **키오스크 UI 접속**
   * 브라우저에서 `http://localhost:8000/` 접속 → 촬영/업로드 후 라인아트 확정 (`phase1_kiosk/confirmed_outputs/latest_lineart.png` 생성)
3. **벡터 경로 추출 실행**
   ```bash
   python3 phase3_path_planner/main.py
   ```
   * 결과는 `phase3_path_planner/outputs/`에 JSON 및 비교 이미지로 저장됩니다.
