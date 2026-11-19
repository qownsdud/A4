# 그림그리기 로봇 프로젝트(A4 퍼즐 드로잉 로봇) 전체 히스토리

이 문서는 두산 협동로봇 `M0609` + OnRobot `RG2` 그리퍼 기반 **A4 퍼즐 드로잉 로봇** 프로젝트의 시작(`2026-11-10`)부터 최신 작업 상태(`2026-11-19 16:51`)까지의 모든 개발 이력을 시간순(`KST, +09:00`)으로 빠짐없이 기록한 연대기입니다.

## 문서 범위 및 참조 자료

- **참조 워크스페이스**
  - `/home/qownsdud/Documents/rokey_collaborate_1`: 초기 기획·사양서·클라우드 AI 실험·로컬 선화(`phase2_lib_lineart`)·키오스크(`phase1_kiosk`)·벡터 경로(`phase3_path_planner`)·파일 관리기(`file_manager.py`)
  - `/home/qownsdud/ws_cobot_pjt/ws_dsr`: ROS 2 Jazzy 로봇 제어·힘/순응 제어 실험·`rokey1`·`pen_test`·`collaborate1`·`art`·실물 실행 로그(`run_logs/`)·미리보기(`drawing_previews/`)
  - `/home/qownsdud/ws_cobot_pjt/A4`: 최종 통합 ROS 2 멀티패키지 워크스페이스(`art_*` 8개 + `vendor/` 9개)·`assets/`·`config/`·`data/`·`docs/`·`pictures/`·`scripts/`·`tests/`·`back/`
  - 보조 산출물: `/home/qownsdud/ws_cobot_pjt/qt_hmi`, `/home/qownsdud/A4` (레거시 경로), `/home/qownsdud/force_test_fz.csv`, `/home/qownsdud/pen_contact_manual.csv`, `/home/qownsdud/Desktop/A4_Drawing.desktop`
- **참조 대화 및 기록**
  - Antigravity 대화 **23건**(브라우저 서브에이전트 2건 및 히스토리 정리 세션 `52b9f5b2` 포함, 총 5,400+ 스텝, 510+ 사용자 요청) 및 아티팩트 `lineart_comparison.md`
  - GitHub `https://github.com/qownsdud/A4` 전 브랜치(`main`, `bae`, `sub`, `yongsoo`, `jang`, `ryu`) 커밋 이력(팀원 `qownsdud`, `TW-94-git`/`jtw`, `RyuM-S`, `dduter` 포함)
  - `colcon build` 이력 총 **445회**(`ws_dsr` 349회 + `A4` 96회), `A4` 작업 기록 **267건**, SQLite 데이터베이스 2종(`jobs_real_v1.db` 3건, `art_state.db` 28건·이벤트 2,325건·복구 체크포인트 6건), 실물 실행 로그(`ws_dsr/run_logs`) 6건
- **표기 원칙**
  - 모든 시각은 한국 표준시(`YYYY-MM-DD HH:MM:SS`) 기준입니다.
  - 대화 출처는 대화 ID 앞 8자리(예: `5efb50cd`), 비대화 기록은 `[파일]`, `[빌드]`, `[Git]`, `[실물로그]` 태그로 표시합니다.
  - API 키, GitHub 토큰, 비밀번호 등 보안에 민감한 정보는 원문을 남기지 않고 `[민감정보 제외]`로 처리했습니다.

## 전체 프로젝트 핵심 이정표 요약

- **2026-11-10 ~ 11-12**: 협동로봇 교육·안전 매뉴얼 학습, 초기 공정 자동화 제안서 작성, 두산 DSL 정리 및 `ws_dsr` ROS 2 Jazzy 워크스페이스 구축(11/12 하루 155회 빌드)
- **2026-11-13**: 그림그리기 로봇 기획 확정, 사양서 3종·파이프라인 문서 작성, 클라우드 AI 선화 실험 → 사람 사진 기반 로컬 선화(`phase2_lib_lineart`)·키오스크(`phase1_kiosk`)·벡터 경로(`phase3_path_planner`) 구축 및 GitHub `qownsdud/A4` 최초 업로드(`a8c6e4b`)
- **2026-11-14 ~ 11-15**: 두산 `M0609` 실기 힘·순응 제어 집중 실험(81회 빌드), 정지마찰 불감대·`moving_baseline`·SVG 드로잉·저속 안전 접촉(`drawingtest_ryu.py`)·`Fz` CSV 정밀 계측, 팀원 오프라인 경로 계획 개발
- **2026-11-16**: `collaborate1` 패키지화·`RyuM-S` `pentest` 통합·`qt_hmi` 구성, 9점 바닥 평면 캘리브레이션 실측, 52자 단선 필기체, 펜 3개·기준 막대 분리 1~14단계 아키텍처 확정, `run_logger` 구축 및 **최초 3펜 분할 인물화 실물 완주(22분 29초)**, 팀원 `TW-94-git`·`yongsoo` 병행 개발
- **2026-11-17**: FastDDS 멀티노트북 진단, `yongsoo` ROS 2 7패키지 통합 및 `AGENTS.md` 도입, `draw_image_standalone.py` 완성, MediaPipe 하이브리드(`lineart_mfl_ld.py`) 확정, Notion 11개 페이지 조사 후 **통합 워크스페이스 `/home/qownsdud/ws_cobot_pjt/A4` 창설**, 안전 잠금 제거·직결·`futex_do_wait` 버그 해결
- **2026-11-18**: `vendor/` 드라이버 편입으로 `A4` 완전 독립 배포화, `JobManager`↔`SQLite`(`art_state_store`) 분리 통합, **TCP `GripperDA_v1` `Z=230mm` 보정 후 A4 통합 첫 실기 완주**, RGB 3색 균일·랜덤 배정 및 개츠비 GrabCut 인물 분리·완주, `ros` 컨트롤러 실기 9연전 디버깅 및 첫 전획 완주, 한글·영문·특수문자 캘리그라피 전면 개편 및 `NanumBrush.ttf` 설치
- **2026-11-19**: 검정 4번 펜(`PEN_4`) 도입·미세 튜닝, 데스크톱 앱 `A4 Drawing Studio` 구축, 가변 필압 캘리그라피·사람 필순·7대 대규모 최적화·곡률 스플라인 감속·`main` 동기화(`464c6ac`), 이어서 **뭉크의 절규(`4d7c6b73`)·영화 대사(`3b83abc6`) 추가 실기 완주 2건(누적 9건)**, `ㅈ`/`ㅝ`·마침표(`.`) 캘리그라피 결손 보정, 슬라이더 즉시 취소 → **`경로 추출` 수동 버튼 전환**, 다국어 정자체(일본어·중국어·러시아어·그리스어·태국어·아랍어·힌디어·움라우트) 지원 및 **`assets/fonts/NanumBrush.ttf` 내장·`scripts/setup_env.bash` 원클릭 배포 환경 구축**

---

## 1장. 사전 준비 및 로봇 제어 기초 구축 (2026-11-10 ~ 2026-11-12)

### 2026-11-10: 초기 자동화 기획 탐색 및 협동로봇 교육 자료 확보

- **2026-11-10 11:16:09** `[파일]` `rokey_collaborate_1/X/cobot_automation_proposal.html` (16,286 bytes) 작성
  - 제목: 「비전 센서 제한 환경에서의 협동로봇 위치·힘 제어 기반 고효율 공정 자동화 시스템 설계 및 경제성 분석」
  - 내용: 그림그리기 로봇 주제 확정 이전에 외부 비전 센서와 LLM 없이 6자유도 협동로봇 위치·속도 제어, 순응/힘 제어, ROS 2(`Topic`, `Service`, `Action`), Python HMI만으로 구현할 후보 주제 3종과 정량 ROI를 비교 정리함.
  - 후보 모델 1: 고온 튀김 조리 및 정밀 탈유 자동화 (`CookMenu.action`, `EmergencyStop.srv`, `/fryer_status`, 인건비 연 약 3,600만 원 절감, 식용유 15% 절감 목표).
  - 후보 모델 2: 중소 제조 공정의 접촉식 불량 전수검사 및 등급 분류 (`InspectBatch.action`, `/measured_height`, `/force_z`, `SetTolerance.srv`, 10 N 접촉 시 TCP Z축 0.1 mm 계측, 사이클 15초 → 5초 단축).
  - 후보 모델 3: 물류 현장의 혼종 박스 높이 감지 및 최적 팔레타이징 (`PalletizeBox.action`, `/pallet_grid_state`, `ResetPallet.srv`, Bin Packing Heuristic 2×2 그리드, 적재 효율 75% → 92% 이상).
- **2026-11-10 11:31:45** `[파일]` `rokey_collaborate_1/manuals/2_협동로봇_중급교육.pdf` (9.63 MB, 146쪽, 두산로보틱스 교육자료) 확보.
- **2026-11-10 11:31:50** `[파일]` `rokey_collaborate_1/manuals/협동로봇_주의사항.pdf` (18.14 MB, 4쪽, 「230926 고정식·이동식 산업용 로봇 협동작업 안내문 OPS 2종」 — 충돌방지 7대 조치 수록) 확보.
- **2026-11-10 11:45:31** `[파일]` `rokey_collaborate_1/manuals/1_협동로봇_초급교육.pdf` (11.30 MB, 151쪽, 두산로보틱스 교육자료) 확보.

### 2026-11-11: 중급 교육 매뉴얼 추가 확보

- **2026-11-11 14:32:30** `[파일]` `rokey_collaborate_1/manuals/3_협동로봇_중급교육.pdf` (7.12 MB, 107쪽, 두산로보틱스 교육자료) 확보.

### 2026-11-12: 두산 DSL 정리 및 `ws_dsr` ROS 2 Jazzy 초기 워크스페이스 실습 (하루 155회 빌드)

- **2026-11-12 09:42:18** `[파일]` `rokey_collaborate_1/DSL기본.txt` (537 bytes) 작성
  - 내용: 두산 협동로봇 기본 DSL 명령 정리 — `move_joint`, `move_task(linear)`, `move_circle`, `moveB`, `sub`/`callsub`, `digital_out_1_release`, `digital_out_2_grasp`, `set`, `wait`, `compliance`(순응제어), `force`(힘제어 — 상대모드 OFF 시 `설정값 + 외력`, 상대모드 ON 시 외력 0 보정으로 `설정값` 유지).
- **2026-11-12 10:10:12 ~ 10:10:13** `[파일]` `/home/qownsdud/ws_cobot_pjt/ws_dsr/src` 초기 ROS 2 Jazzy 워크스페이스 구축
  - 기반 저장소: `ahnisinc/cobot_rg2` (`4d5657f`, Ubuntu 24.04 + ROS 2 Jazzy + Doosan DRCF 에뮬레이터 구성).
  - 포함 패키지: `doosan-robot2`(`dsr_bringup2`, `dsr_common2`, `dsr_controller2`, `dsr_description2`, `dsr_example2`, `dsr_gazebo2`, `dsr_hardware2`, `dsr_mobile_wbc2`, `dsr_moveit2`, `dsr_msgs2`, `dsr_tests`, `install_emulator.sh`), `onrobot-ros2`(`onrobot_rg_control`, `onrobot_rg_description`, `_onrobot_rg_modbus_tcp`, `onrobot_rg_msgs`), `rg2/m0609_rg2_bringup`(M0609+RG2 통합 URDF/xacro, `mount_bracket.stl`, RViz 설정, `bringup.launch.py`, `bringup_camera.launch.py`, `new_bringup.launch.py`, 가상/조인트 퍼블리셔), `rokey`(교육 패키지 `simple_move`, `simple_input`, `moveit_demo`).
- **2026-11-12 10:17:03 ~ 10:20:27** `[빌드]` `ws_dsr` 최초 전체 `colcon build` 완료 (`build_2026-11-12_10-17-03`, 35개 패키지, 203.6초 소요, 종료 코드 `0`).
- **2026-11-12 11:16:20** `[파일]` 사용자 실습 패키지 `ws_dsr/src/rokey1` 생성 (`LICENSE`, `setup.cfg`, `resource/rokey1`, `rokey1/__init__.py`, `test/*`).
- **2026-11-12 11:21:08 ~ 14:20:23** `[빌드]` `rokey1/move.py`(`simple_move` 엔트리포인트) 작성 및 반복 빌드 23회 (`build_2026-11-12_11-21-08` ~ `14-20-12`).
- **2026-11-12 14:46:33 ~ 14:56:36** `[빌드]` `rokey1/setup.py` 문법·파싱 오류(`CalledProcessError` in `run_setup('setup.py')`)로 10회 연속 빌드 실패. 도중 **14:50:59**에 `src/rokey1/package.xml`(`rclpy`, `std_msgs`, `action_msgs`, `dsr_msgs2`, `dsr_common2` 의존성) 수정.
- **2026-11-12 14:57:57 ~ 15:56:31** `[빌드/파일]` `rokey1/grip_text.py`(엔트리포인트 `grip_test`, 파일명 오타 `grip_text.py`) 추가 및 16회 테스트 빌드
  - 내용: `ROBOT_ID="dsr01"`, `ROBOT_MODEL="m0609"`, `Tool Weight_1`, `GripperDA_v1`, `VELOCITY=30`, `ACC=30`, `homej=[0,0,90,0,90,0]`, `set_digital_output(1, ON)`/`(2, ON)` 파지·놓기 3회(`CYCLE=3`) 반복 및 `time.perf_counter()` 소요 시간 측정. **15:56:18** 최종본(2,481 bytes)이 이후 `collaborate1_codeback/grip_text.py` 및 `collaborate1/experiments/grip_text.py`로 보존됨.
- **2026-11-12 17:01:36 ~ 21:33:32** `[빌드/파일]` `rokey1/gear.py`(기어 이송 및 순응·힘·주기운동 조립) 집중 개발 — **103회 빌드** (11/12 하루 총 **155회** `colcon build`)
  - **17:01:36**: `gear.py` 최초 빌드 반영.
  - **17:02:49**: `setup.py`에 `gear` 엔트리포인트 등록(`gear`, `grip_test`, `simple_move` 3종).
  - **18:20:53**: `rokey1/move.py`(2,570 bytes) 최종 수정 — Joint(`J_VEL=100, J_ACC=100`)·Linear(`L_VEL=300, L_ACC=300`) 속도 분리, `Tool_Weight`, `GripperDA_v1`, 4개 관절 포즈(`posj1`~`posj4`)·`posx1`/`posx2` 3회 반복, `Ctrl+C` 블로킹 방지 정리.
  - **21:33:32**: `rokey1/gear.py`(3,619 bytes) 최종 저장 — 4개 기어(`p1x`, `p3x`, `p2x`, `p0x`) 픽앤플레이스(`deliever_gear`, `up/down=±48 mm`, `mv=+300 mm Y`) 및 마지막 기어 조립(`deliever_lastgear`: `lastdown=-28 mm`, `task_compliance_ctrl()`, `set_stiffnessx([3000,3000,3000,200,200,200], time=0.3)`, `set_desired_force([0,0,-20,0,0,0], dir=[0,0,1,0,0,0], mod=DR_FC_MOD_REL)`, `move_periodic(amp=[0,0,0,0,0,10], period=[0,0,0,0,0,1], repeat=2, ref=DR_TOOL)`).

---

## 2장. 그림그리기 로봇 기획, Phase 1~3 프로토타입 및 첫 GitHub 업로드 (2026-11-13)

*(당일 `ws_dsr` 빌드는 0회이며, 모든 작업이 `/home/qownsdud/Documents/rokey_collaborate_1`에서 진행됨.)*

### 10:19 ~ 10:43: 아이디어 실현성 검토 및 사양서 3종 작성

- **2026-11-13 10:19:58 ~ 10:20:57** (`5efb50cd`) `아이디어.txt` AI 채택 및 구동 가능성 검토
  - 사용자 질의: `아이디어.txt`(실물 라인아트 그림 생성기 — 러프 스케치 + 키워드 3개 → AI 라인아트 → 동작 프로그램)에 기술된 AI의 실제 채택·구동 가능성 확인.
  - 검토 결과: 2~3단계(클라우드 API OpenAI/Gemini 또는 로컬 SDXL+ControlNet + 고정 시스템 프롬프트)는 실현 가능성이 높으나, 4~5단계 "픽셀 정보대로 그림을 그림"은 소요 시간·잉크 번짐·관절 마모 문제로 부적합함. 대안으로 **OpenCV(`findContours`, 세선화, `approxPolyDP`)/Potrace 벡터 경로(Waypoint) 변환 + 스프링 탄성 펜 홀더 + 3개 ROS 2 노드 구조** 제안.
- **2026-11-13 10:34:22 ~ 10:34:50** (`5efb50cd`) 사양서 3종 최초 작성(오타 폴더 `specificationn/`)
  - 사용자 요청으로 오타 폴더명 `specificationn/` 아래 3개 문서 생성:
    - `1_ai_lineart_generation.txt`: 입력 규격, 옵션 A(클라우드 API) vs 옵션 B(로컬 SD+ControlNet), 프롬프트 전략, 예외 처리
    - `2_vector_path_extraction.txt` (`10:34:48` 확정, 3,417 bytes): OpenCV 4단계(이진화 → 세선화 → `approxPolyDP` → 노이즈 제거/TSP), 로봇 좌표 매핑, Stroke JSON 포맷
    - `3_ros2_hardware_integration.txt`: 스프링 탄성 펜 홀더(3~5 mm 유격), 목표 시간 1분 30초~3분, `kiosk_ui_node`·`path_planner_node`·`robot_drawer_node`, 안전 체크리스트
- **2026-11-13 10:35:39 ~ 10:35:43** (`5efb50cd`) 사용자가 폴더명을 `specificationn` → `specification`으로 정정하고 에이전트에 공유.
- **2026-11-13 10:39:24 ~ 10:43:07** (`39951373`) 옵션 A(클라우드 API) 구체 구현 과정 설계
  - `10:39:24` 구체 구현 과정 요청 → `10:43:07` 명료 요약 재요청에 따라 5단계 구현안(FastAPI+`.env` 키 관리 → `512×512`/`1024×1024`·RGBA→순백색 정규화·금칙어/번역 → 고정 시스템 프롬프트+3~10초 타임아웃/1회 재시도 → 이진화·빈 이미지 검증·용지 비율 맞춤 → 키오스크 로딩 UI/오류 안내) 정리.

### 11:10 ~ 11:28: 전체 업무 파이프라인 통합 문서화 및 Phase 1·3·4·5 동시 킥오프

- **2026-11-13 11:10:12 ~ 11:11:50** (`194ddcd7` 1차) `아이디어.txt`, `DSL기본.txt`, 사양서 3종, `X/cobot_automation_proposal.html`을 종합해 `전체_업무_파이프라인.txt` 초안(Stage 1~5) 작성.
- **2026-11-13 11:15:28 ~ 11:18:02** (`194ddcd7` 2차 재실행) 사용자가 "이 프로젝트의 모든 대화를 참고하여 업데이트가 필요한 파일은 업데이트하라"고 보완 요청 → 이전 대화(`5efb50cd`, `39951373`) 및 `manuals/*.pdf` 4종까지 전부 스캔해 `전체_업무_파이프라인.txt`(Phase 1~5, 두산 DSL 매핑, 예외 대응 매트릭스, `협동로봇_주의사항.pdf` 충돌방지 7대 조치, 통합 검증 체크리스트) 재작성 및 `specification/1_ai_lineart_generation.txt`(옵션 A 구현 절차 추가), `specification/3_ros2_hardware_integration.txt`(`11:18:02` 확정, 4,395 bytes, DSL 매핑·충돌방지 7대 조치 반영) 갱신.
- **2026-11-13 11:26:36** `[파일]` `아이디어.txt`(2,525 bytes) 최종 수정 — 5단계를 `"픽셀 정보를 벡터 정보로 변환 후, 그대로 그림을 그림"`으로 보완하고 1~9장(요구사항, draw.io 아키텍처, 작업 흐름, ROS 2 구조, 장비 목록, 네트워크, 인터페이스, HMI/UI 디자인) 목차 정리.
- **2026-11-13 11:27:17 ~ 11:27:31** (`1eeef029`) **Phase 1 킥오프**: Python 3.12.3 환경 확인 후 `venv`·이미지 정규화/키워드 정제·키오스크 UI 프로토타입 순서 및 웹 UI vs Python GUI 선택지 제시.
- **2026-11-13 11:27:55 ~ 11:28:31** (`eca9173a`, `11:27:55` 입력 후 `11:28:05` 동일 재전송) **Phase 3 킥오프**: `cv2` 4.6.0(`cv2.ximgproc.thinning` 지원), `numpy`, `scipy`, `matplotlib`, `PIL` 설치 확인 후 `image_to_strokes` → 시각화/KPI 검증 → `pixels_to_robot` 순서 제시.
- **2026-11-13 11:28:31 ~ 11:28:52** (`4f91a1ce`) **Phase 4 킥오프**: `/opt/ros/jazzy/bin/ros2` 확인 후 `drawing_interfaces`(`DrawStrokes.action`)·`robot_drawer` 패키지 및 두산 ROS 2/DSL 연동 시퀀스 제안.
- **2026-11-13 11:28:41 ~ 11:28:58** (`6d804672`) **Phase 5 킥오프**: 완료/초기화 상태 머신, 예외 대응 매트릭스, 충돌방지 7대 조치 체크리스트 및 드라이런·E-Stop 검증 절차 제안.

### 11:39 ~ 12:58: Phase 2-A 클라우드 AI (`phase2_ai_lineart/`) 구축 및 스타일 실험

- **2026-11-13 11:39:34 ~ 11:39:39** `[파일]` `phase2_ai_lineart/.gitignore` 및 `.venv` 생성.
- **2026-11-13 11:51:11** `[파일]` `project_self_feedback.jpg` (114,280 bytes, WebP 형식 시스템 공학 **V-Model** 다이어그램: Concept of Operations → Requirements & Architecture → Detailed Design → Implementation → Integration/Test/Verification → System V&V → Operation & Maintenance) 저장.
- **2026-11-13 11:52:33** `[파일]` `.vscode/settings.json` (`"python.terminal.useEnvFile": true`) 생성.
- **2026-11-13 11:59:21** `[파일]` `phase2_ai_lineart/requirements.txt` (`httpx`, `pillow`, `opencv-python`, `numpy`, `python-dotenv`, `fastapi`, `uvicorn`, `python-multipart`) 작성.
- **2026-11-13 12:02:38** `[파일]` `phase2_ai_lineart/samples/cat_sketch.jpg` (32,727 bytes, 테스트용 러프 고양이 스케치) 저장.
- **2026-11-13 12:44:20 ~ 12:46:16** `[파일]` Cloudflare Workers AI 기반 라인아트 6종 스타일 비교 실험 출력 생성:
  - `outputs/style_1_fine_line.png` (`12:44:20`), `style_2_contour.png` (`12:44:22`), `style_3_continuous.png` (`12:44:23`), `style_4_editorial.png` (`12:44:25`), `style_art_minimal.png` (`12:46:14`), `style_art_oneline.png` (`12:46:16`).
- **2026-11-13 12:51:04 ~ 12:51:09** `[파일]` `phase2_ai_lineart/.env.example`, `config.py`, `.env` (`[민감정보 제외]`) 확정
  - 모델·파라미터: Cloudflare Workers AI `@cf/black-forest-labs/flux-2-klein-4b`, `timeout_sec=30.0`, `max_retries=1`, `sketch_size=512`, `PAPER_RATIOS`(`a4: (210, 297)`, `postcard: (100, 148)`, `square: (1, 1)`), `SYSTEM_PROMPT_TEMPLATE`, `NEGATIVE_PROMPT`.
  - 연동 모듈: `ai_client.py`(`check_internet_health`, `generate_lineart`), `postprocess.py`(`normalize_sketch_bytes`, Otsu 이진화·`MORPH_CLOSE`·검정 픽셀 비율 `0.003~0.70` 검사·용지 패딩), `app.py`(`GET /health`, `POST /generate-lineart`), `test_pipeline.py`.
- **2026-11-13 12:58:47** `[파일]` `phase2_ai_lineart/outputs/hf_kontext_finepen.png` (20,400 bytes, Hugging Face Kontext 파인펜 스타일 비교 출력) 생성.

### 14:15 ~ 14:59: 사진 기반 로컬 선화(`phase2_lib_lineart/`) 전환 및 `file_manager.py` 제작

- **2026-11-13 14:15:15 ~ 14:16:18** (`5d83d589`) **기획 방향 전환 — 러프 스케치+키워드 → 사람 사진 입력**
  - 사용자 요청: 사진을 입력받아 방식 A(`controlnet_aux` `LineartDetector`)와 방식 B(`OpenCV` Color Dodge / Canny+bilateralFilter)로 선화 변환하는 모듈 구축.
  - 환경 확인: Python 3.12.3, `uv` 사용 가능, `nvidia-smi` 미감지(CPU 추론 환경).
- **2026-11-13 14:19:23 ~ 14:21:46** (`5d83d589`) `phase2_lib_lineart/` 구축 및 최초 CPU 벤치마크
  - `phase2_lib_lineart/.venv` 생성 및 `uv pip install`(`torch`, `torchvision`, `controlnet-aux`, `transformers`, `opencv-python`, `pillow`, `numpy`), `requirements.txt`·`utils.py`·`lineart_dl.py`·`lineart_cv.py`·`main.py` 작성.
  - `cat_sketch.jpg` 테스트: `OpenCV:canny` `39.5 ms`, `OpenCV:dodge` `36.8 ms`, `DL:LineartDetector (cpu)`(`sk_model.pth` 다운로드 후) 로드 `0.48 s` / 추론 `1.03 s`.
- **2026-11-13 14:24:17** `[파일]` 인물 샘플 사진 `phase2_lib_lineart/samples/person1.jpg` (670,022 bytes) 저장.
- **2026-11-13 14:26:00 ~ 14:26:18** (`5d83d589`) `person1.jpg` 5모드 CPU 벤치마크
  - `LineartDetector` 기본: 로드 `0.51 s` / 추론 `1.15 s` (`person1_dl.png`)
  - `LineartDetector --coarse`: 로드 `0.52 s` / 추론 `1.14 s` (`person1_dl_coarse.png`)
  - `OpenCV dodge`: `114.0 ms` (`person1_cv_dodge.png`)
  - `OpenCV canny`: `92.0 ms` (`person1_cv_canny.png`)
  - `OpenCV adaptive`: `101.2 ms` (`person1_cv_adaptive.png`)
- **2026-11-13 14:27:52** (`5d83d589` 초안 취소) → **14:28:11 ~ 14:35:28** (`a35129b6`) **YAML 기반 파일 관리기 `file_manager.py` 제작**
  - 사용자 요청: 파일명 확인·수정을 한곳에서 YAML로 관리하고 트리 구조가 실시간 표시되는 도구 요청.
  - 산출물: `file_manager.py`(13,727 bytes, `watch`/`sync`/`tree`/`apply`/`--dry-run` 및 `_rename_dir` 지원), `test_file_manager.py`(3,869 bytes, 단위 테스트 4건 통과), `files.yaml` 생성·동기화(`14:35:08 ~ 14:35:25`).
- **2026-11-13 14:33:38 ~ 14:35:06** (`5d83d589`, `14:34:21` 재시도) `LineartDetector` 잔선 축소 옵션 구현
  - 사용자 피드백: 방식 A가 가장 마음에 들지만 선의 양이 너무 많음.
  - 구현: `utils.py`, `lineart_dl.py`, `main.py`에 `--pre-smooth N`(`cv2.bilateralFilter` N회), `--line-threshold T`(강도 임계값), `--min-line-area A`(`connectedComponentsWithStats` 소면적 잡선 제거) 3옵션 추가.
  - 비교 테스트: 기본+정리(`--pre-smooth 2 --line-threshold 160 --min-line-area 30`, 추론 `1.36 s`) vs Coarse+강정리(`--coarse --pre-smooth 2 --line-threshold 150 --min-line-area 40`, 추론 `1.32 s`).
- **2026-11-13 14:40:55** (`5d83d589`) 사용자 옵션 조절법·`outputs/` 경로 질의 및 CLI 안내.
- **2026-11-13 14:50:07 ~ 14:51:16** (`5d83d589`) 로컬 DL 최적 파라미터 확정
  - 사용자 직접 튜닝 확정값: `--pre-smooth 2 --line-threshold 200 --min-line-area 5` → `LineartDLConfig` (`lineart_dl.py`)와 `main.py` 기본값으로 고정(`binarize=True`, 로드 `0.71 s` / 추론 `1.27 s`, `outputs/person1_dl_smooth2_clean.png`). Phase 2 핵심 완료 확인 후 Phase 3 진입 제안.
- **2026-11-13 14:52:26 ~ 14:54:23** (`39951373`) 전체 진척 검토 및 문서 갱신 — `전체_업무_파이프라인.txt`에 `phase2_ai_lineart`·`phase2_lib_lineart` 현황 반영 및 `file_manager.py sync`.
- **2026-11-13 14:57:18 ~ 14:57:33** (`1eeef029`) Phase 1 웹캠 키오스크 설계 — FastAPI(`http://localhost:8000`) 웹 서버 + 노트북 카메라 직접 촬영 구조 확정.
- **2026-11-13 14:59:05 ~ 14:59:48** (`39951373`) OpenCV Canny 우선 논의 및 문서 반영
  - 사용자 요청: AI 대신 "canny엣지라이브러리" 우선 적용 요청 및 용어 확인.
  - 조치: **OpenCV `cv2.Canny` 엣지 검출 알고리즘**으로 용어 정정(키워드 창작 불가·윤곽선 추출 전용), `specification/1_ai_lineart_generation.txt`(옵션 C 추가, `14:59:32` 5,082 bytes), `전체_업무_파이프라인.txt`, `lineart_cv.py`/`main.py`(기본 `--method cv --cv-mode canny`) 갱신 및 검증(`79.3 ms` → `outputs/person1_cv_canny.png`).

### 15:01 ~ 16:08: Phase 1 키오스크 구현, `lineart_onetouch` 실험, `X/` 아카이브 및 로컬 DL 카메라 전용 확정

- **2026-11-13 15:01:05 ~ 15:03:46** (`1eeef029`) **`phase1_kiosk/` 최초 구현**
  - 생성 파일: `phase1_kiosk/preprocess.py`(금칙어/영문 매핑, 빈 캔버스 차단, `normalize_photo_bytes`), `server.py`(`GET /`, `GET /api/health`, `POST /api/kiosk/sketch`, `POST /api/kiosk/photo`), `static/{index.html, style.css, app.js}`.
  - 기능: 러프 스케치 캔버스+키워드 3개 모드, 노트북 웹캠(WebRTC `getUserMedia`, 좌우 반전, 즉시/3초 타이머 촬영, 파일 업로드 폴백), 결과 미리보기·PNG 다운로드. `TestClient` 통과(`cv_dodge`, `576×815`, `0.03 s`).
- **2026-11-13 15:24:42 ~ 15:26:43** (`1eeef029`) **Cloudflare 429 할당량 소진 확인 및 로컬 DL 3단계 디테일 도입**
  - 사용자 보고: 러프 스케치 그리기 오류 + 사진 선화 방식은 로컬 딥러닝으로 고정하고 디테일 선택 기능 추가 요청.
  - 원인 규명: Cloudflare 무료 할당량(10,000 neurons/일) 소진으로 HTTP `429`(code `4006`) 발생 확인 → 사용자 친화 오류 메시지 및 `X-Keywords-Used` URL 인코딩 적용.
  - `DL_DETAIL_PRESETS` 3단계 구현:
    - `high` (세밀하게): `coarse=False, pre_smooth=0, line_threshold=220, min_line_area=2`
    - `medium` (표준): `coarse=False, pre_smooth=2, line_threshold=200, min_line_area=5`
    - `low` (단순하게): `coarse=True, pre_smooth=3, line_threshold=170, min_line_area=15`
- **2026-11-13 15:34:49 ~ 15:35:12** (`1eeef029`) **디테일 프리셋 1차 재조정**
  - 사용자 요청: 기존 표준을 단순하게로 내리고, 세밀하게~표준 중간을 표준으로 설정.
  - 변경 수치: `medium` → `pre_smooth=1, line_threshold=210, min_line_area=3`(선 비율 `0.0543`, `4.40 s`), `low` → `pre_smooth=2, line_threshold=200, min_line_area=5`(선 비율 `0.0354`, `4.46 s`).
- **2026-11-13 15:37:20 ~ 15:38:10** (`1eeef029`) **`사진 최종 선택` 버튼 및 확정 저장소 구현**
  - `PNG 다운로드` → `사진 최종 선택`으로 변경, `POST /api/kiosk/confirm`·`GET /api/kiosk/latest` 추가 → `phase1_kiosk/confirmed_outputs/latest_lineart.png`, `latest_meta.json`, `history/lineart_20261113_153810.png` 첫 저장 검증.
- **2026-11-13 15:44:24 ~ 15:46:29** (`1eeef029`) **`lineart_onetouch/` 한붓그리기 분기 실험**
  - 사용자 요청으로 `phase1_kiosk/`를 보존한 채 `lineart_onetouch/`(`onetouch.py`, `preprocess.py`, `server.py`, `static/*`) 별도 제작 — 형태학적 세선화 → 8-이웃 추적 → `approxPolyDP` → TSP 정렬+방향 반전 단일 연속선(`stroke_count=1`). `person1.jpg` 결과: `344선 → 1붓(973점)`, `4.54 s`, `latest_onetouch_path.json` 및 `history/lineart_20261113_154629.png` 생성.
- **2026-11-13 15:48:36 ~ 15:49:43** (`1eeef029`) **`lineart_onetouch/` 거리 임계값 기반 최소 획수 방식 전환**
  - 사용자 피드백: 무조건 한붓 대신 가까운 선만 잇고 먼 선은 끊어 최소 획수로 구성.
  - 수정: `max_connect_dist=15.0 px` 이하만 연결. `person1.jpg` 결과: `344선 → 93획`(`973점`, `4.59 s`, 그리기 `8908.5 px`, 공중 이동 `4467.7 px`, `X-Stroke-Count`/`X-Original-Strokes` 헤더 추가, `history/lineart_20261113_154943.png`).
- **2026-11-13 15:57:44 ~ 15:57:57** `[파일]` 사용자가 보류·실험 폴더 `phase2_ai_lineart/`와 `lineart_onetouch/`를 `X/` 아카이브로 이동 (VS Code 이동 시 `X/phase2_ai_lineart/{ai_client, test_pipeline, app, postprocess}.py` import 경로가 `X.phase2_ai_lineart.*`로 자동 갱신됨).
- **2026-11-13 15:59:06 ~ 16:00:43** (`1eeef029` 1차 시도) 사용자가 `phase2_lib_lineart` 단독 채택 및 AI 러프 스케치·키워드 제거를 지시하며 "캐니엣지"로 입력 → `phase1_kiosk`를 `LineartConverterCV(mode="canny")` 전용으로 단순화하고 **`phase2_lib_lineart/.venv`에 `fastapi`, `uvicorn`, `python-multipart`, `httpx` 통합 설치** (`high 0.024 s` / `medium 0.024 s` / `low 0.026 s`, `history/lineart_20261113_160043.png`).
- **2026-11-13 16:02:20 ~ 16:03:22** (`1eeef029` 수정 재실행) 사용자가 "캐니엣지"를 **"카메라"**로 정정 → `/api/kiosk/sketch` 완전 제거, 접속 즉시 **노트북 카메라 + `phase2_lib_lineart` 로컬 DL(`high`/`medium`/`low`)** 전용으로 `server.py`·`index.html`·`app.js` 재구성(`dl_ready: True`, `512×724`, `4.80 s`, `history/lineart_20261113_160322.png`).
- **2026-11-13 16:04:42** `[파일]` 사용자 실전 키오스크 최종 선택 테스트 (`history/lineart_20261113_160442.png`, 6,710 bytes).
- **2026-11-13 16:05:58 ~ 16:06:40** (`1eeef029`) 확정 파일 관리 정책 개편 — `POST /api/kiosk/confirm` 시 직전 `latest_lineart.png`를 `history/lineart_YYYYMMDD_HHMMSS_ffffff.png`로 `shutil.move` 이동하고 `latest_meta.json`은 삭제·미생성, `GET /api/kiosk/latest`는 PNG에서 직접 해상도 반환하도록 수정(`history/lineart_20261113_160640_506229.png` 생성; 테스트용 빈 흰 이미지가 일시적으로 `latest_lineart.png`에 남음).
- **2026-11-13 16:07:45 ~ 16:08:52** (`39951373`) `전체_업무_파이프라인.txt`(`16:08:11`, 13,220 bytes) 및 `files.yaml` 최신화.

### 16:09 ~ 16:45: Phase 3 벡터 경로 추출기(`phase3_path_planner/`) 구현·4단계 품질 튜닝 및 실전 연동

- **2026-11-13 16:09:33 ~ 16:09:50** (`eca9173a`) Phase 3 정보 최신화 — 샘플 3종(`latest_lineart.png`, `person1_cv_canny.png`, `person1_dl_smooth2_clean.png`) 확인 및 모듈 구성 보고.
- **2026-11-13 16:10:37 ~ 16:11:50** (`eca9173a`) **`phase3_path_planner/` v1 구현**
  - 파일: `extractor.py`(이진화 → `cv2.ximgproc.thinning` → 연속 Stroke 추적 → `cv2.approxPolyDP` `epsilon=1.5` → `min-length=5.0` → Nearest-Neighbor TSP), `visualize.py`(`*_vector.png`, 3단 비교 `*_comparison.png`), `main.py`(`*_strokes_px.json`).
  - 검증: `latest_lineart.png`가 빈 흰 테스트 이미지임을 발견해 `history/lineart_20261113_160322.png`(`0.078 s`, `340`획, `9,571 → 757점` `92.1%` 절감) 및 `person1_dl_smooth2_clean.png`(`0.078 s`, `404`획, `11,591 → 894점` `92.3%` 절감) 변환 검증.
- **2026-11-13 16:20:23 ~ 16:20:32** (`eca9173a`) 사용자가 `latest_lineart.png`를 실제 촬영본으로 갱신 후 재확인 → v1 결과 `0.037 s`, `95`획, `2,897 → 204점`(`93.0%` 절감), 그리기 `1514.8 px`, Pen-Up `1946.1 px`.
- **2026-11-13 16:21:59 ~ 16:22:33** (`eca9173a`) **v2 개선 (무손실 간선 추적)**: 사용자 "너무 단순함" 피드백 → 분기점 끊김 없는 간선(Edge) 기반 스켈레톤 추적, `epsilon` `1.5 → 0.6`, `min-length` `5.0 → 2.0`, `thickness=2 px` 적용 → `0.039 s`, `181`획, `4,146 → 560점`(`86.5%` 절감).
- **2026-11-13 16:24:38 ~ 16:25:48** (`eca9173a`) **v3 전면 개선 (Hybrid 굵은 영역 외곽선 + 끝점 연결 + Chaikin 스무딩)**: 사용자 "안 예쁨" 피드백 → `cv2.distanceTransform`으로 눈동자·콧구멍·입술·머리카락 등 굵은 영역을 판별해 `cv2.findContours` 외곽선 병행 추출, `_bridge_close_strokes`(`4.5 px` 이내 끊어진 끝점 자동 연결), `_chaikin_smooth` 곡선 스무딩, `epsilon=0.45`, 2배 업스케일 안티앨리어싱 적용 → `0.347 s`, `115`획, `5,677 → 1,911점`(`66.3%` 절감). (`extractor.py` `16:25:11` 12,566 bytes 확정).
- **2026-11-13 16:27:00 ~ 16:29:13** (`eca9173a`) **v4 세필 렌더링(`0.5 px` 상당)**: "선 두께 축소"(`thickness=1`, `16:27:21`) → "달라진 게 없다, 벡터는 두께 표현 불가?" 질의 → `0.5 px` 상당 세필 렌더링 재적용(`visualize.py` `16:29:06` 3,502 bytes) 및 고정 펜 굵기 제약·외곽선(Contour) vs 내부 해칭(Hatching) 설명.
- **2026-11-13 16:34:14 ~ 16:34:53** (`eca9173a`) Phase 3 기본 스타일 확정 및 `outputs/history/` 자동 타임스탬프 아카이브 도입(`main.py` `16:34:44` 4,453 bytes, 기존 출력 9건 이동, `file_manager.py sync`).
- **2026-11-13 16:37:03** (`eca9173a`) **캘리브레이션 보류 합의**: 사용자가 "그리퍼로 펜을 잡아야 해 TCP 재설정이 필요하므로 하드웨어 검증 후 캘리브레이션 진행" 제안 → 하드웨어 실측 3요소(펜촉 TCP·수직 자세, 종이 지그 4점, `Z_draw`/`Z_up`) 정리 후 Phase 3 완료 합의.
- **2026-11-13 16:41:56 ~ 16:45:53** `[파일]` + (`eca9173a` `16:42:39 ~ 16:42:45`) 키오스크 → 벡터화 수동 연동 실전 테스트 2회
  - `16:41:56`: 키오스크 최종 선택(12,424 bytes) → `16:42:39` 확인 방법 질의 → `16:43:43` `phase3_path_planner/main.py` 실행.
  - `16:45:44`: 키오스크 최종 선택 2회차(**10,942 bytes** — 이 이미지가 11/16 `ws_dsr/src/collaborate1/collaborate1/test_image/test_image.png`로 복사되어 **최초 실물 로봇 3펜 인물화 테스트 기준 이미지**가 됨) → `16:45:52 ~ 16:45:53` `phase3_path_planner/main.py` 재실행 완료.

### 17:29 ~ 17:54: 실행 명령 정리 및 GitHub(`qownsdud/A4`) 최초 업로드

- **2026-11-13 17:29:12** `[파일]` `rokey_collaborate_1/실행코드.txt` (347 bytes) 작성 — 1) 키오스크 uvicorn 서버 실행, 2) `http://localhost:8000/` 접속, 3) `python3 phase3_path_planner/main.py` 벡터화 실행 명령 정리.
- **2026-11-13 17:43:38 ~ 17:47:43** (`a73748f9`) + `[Git]` **최초 커밋 `a8c6e4b`**
  - 사전 점검: Git 미초기화, `phase2_lib_lineart/.venv` 약 `5.9 GB`·`X/phase2_ai_lineart/.venv` 약 `343 MB`(GitHub 100 MB 제한 초과), `.env` 민감 파일 확인.
  - 사용자 지정: 저장소 `https://github.com/qownsdud/A4`, 계정 `qownsdud`, 민감 파일 및 `X/` 제외.
  - 조치: `.gitignore` 생성(`.venv/`, `venv/`, `__pycache__/`, `*.py[cod]`, `.env`, `.env.*`, `!.env.example`, `*.pem`, `*.key`, `.vscode/`, `.DS_Store`, `X/`), `git init -b main`, 총 **58개 파일** 초기 커밋 **`a8c6e4b`** (`2026-11-13 17:47:43`, `Initial commit: upload project files (excluding .venv, .env, X, and cache)`).
- **2026-11-13 17:49:39 ~ 17:54:03** (`a73748f9`) GitHub 인증 트러블슈팅 및 최초 푸시 성공
  - `17:49:39`: 일반 계정 비밀번호 입력으로 `Password authentication is not supported` 실패 → PAT 발급(`repo` 권한) 및 `credential.helper store` 안내.
  - `17:52:39`: 권한 부족 `403`(`Permission to qownsdud/A4.git denied`) 발생 → Fine-grained `Contents: Read and write` / Classic `repo` 체크 및 `~/.git-credentials` 초기화 안내.
  - `17:53:40 ~ 17:54:03`: `git push -u origin main` 성공 (`68 objects`, `41.57 MiB`, `main -> main` 최초 업로드 완료).

---

## 3장. 두산 M0609 실기 힘·순응 제어 집중 실험 및 센서 정량 계측 (2026-11-14 ~ 2026-11-15)

*(2026-11-14 하루 `ws_dsr`에서 총 **81회** `colcon build` 수행, 대화 `e109e205` 전반부 44개 사용자 요청 집중 진행.)*

### 12:40 ~ 13:19: 초기 `drawingtest1.py`, `DSR_ROBOT2` `ImportError` 해결 및 DRL V2.12.1 매뉴얼 대조

- **2026-11-14 12:40:09** `[파일]` `ws_dsr/src/doosan-robot2/test/drawingtest1.py` (1,702 bytes) 생성
  - `gear.py` 템플릿 기반 초기 드로잉 테스트: `ROBOT_ID="dsr01"`, `ROBOT_MODEL="m0609"`, `J_VEL/J_ACC=60/60`, `L_VEL/L_ACC=100/100`, `TOOL_NAME="Tool_Weight"`, `TCP_NAME="GripperDA_v1"`, `homej=[0,0,90,0,90,0]`, `task_compliance_ctrl()` → `set_stiffnessx([3000,3000,3000,200,200,200], time=0.3)` → `set_desired_force([0,0,-20,0,0,0], dir=[0,0,1,0,0,0], time=0.3, mod=DR_FC_MOD_REL)` → `release_force()` → `release_compliance_ctrl()`.
- **2026-11-14 12:49:52 ~ 13:01:25** `[빌드]` 7회 연속 빌드 — `12:51:35`에 `rokey1/drawingtest1.py` 최초 복사, `13:01:18`에 `rokey1` `drawing_test1` 엔트리포인트 최초 등록.
- **2026-11-14 13:04:49 ~ 13:10:35** (`e109e205` #1~#4) `get_force_control_state` `ImportError` 및 DRL 매뉴얼 대조
  - 오류 (`13:04:49`, `13:05:56` 재전송): `cannot import name 'get_force_control_state' from 'DSR_ROBOT2'` 및 후속 `NameError: name 'posj' is not defined`.
  - 원인: DRL 매뉴얼 함수 `get_force_control_state`가 ROS 2 `DSR_ROBOT2.py` 래퍼에 미구현 상태이며, `try...except ImportError`가 종료하지 않아 `from DR_common2 import posx, posj`가 건너뛰어짐.
  - 매뉴얼 조사 (`13:09:17`): 두산 V2.12.1 프로그래밍 매뉴얼(`__pagetree.json`) 12개 대분류 **452페이지** 전체 구조 확인.
  - 수정 (`13:10:35`): `get_force_control_state` → `get_tool_force()` 교체, `except ImportError`에서 `raise` 처리(`13:18:48`, `13:19:01` 빌드).

### 13:22 ~ 14:50: 순응/힘 제어 3단계 설계부터 정지마찰 불감대·`moving_baseline` 실기 반복 실험

- **2026-11-14 13:22:32 ~ 13:27:40** (`e109e205` #5~#7) 순응/힘 제어 3단계 드로잉 최초 구현 및 상단 파라미터 통합
  - 설계 및 구현: ① `task_compliance_ctrl(stx=[3000,3000,800,200,200,200])`(XY 고강성, Z 저강성), ② `touch_paper()`(`-2.0 mm` × 최대 40스텝 하강 + `check_force_condition(DR_AXIS_Z, min=3.0, ref=DR_BASE)`), ③ `set_desired_force([0,0,-5.0,0,0,0], dir=[0,0,1,0,0,0], time=0.3, mod=DR_FC_MOD_REL)` 유지하며 `50×50 mm` 사각형 `movel` 그리기 + `try...finally` 안전 해제. 상단 파라미터 블록 통합(`13:27:40`) 및 빌드(`13:45:47`).
- **2026-11-14 13:29:49 ~ 13:34:20** (`e109e205` #8~#11) `task_compliance_ctrl`·`set_stiffnessx`·`time` 파라미터 동작 원리 규명
  - `task_compliance_ctrl(stx, time=0)`의 기본 Z 강성(`3000 N/m`) vs `set_stiffnessx` 기본(`500 N/m`), 2번째 인수(`time` vs `ref`) 혼동 주의, `time`은 전진 시간이 아닌 `0.0~1.0 s` 램프 전환 시간임을 `DSR_ROBOT2.py`·`dsr_controller2.cpp`·V2.12.1 매뉴얼로 확인.
- **2026-11-14 13:48:29 ~ 13:53:54** (`e109e205` #12~#13) 허공 조기 감지 해결
  - 사용자가 `READY_OFFSET` `-100 → -70` 조정 후(`13:51:55`, `13:52:58` 빌드) 공중에서 사각형이 그려지는 문제 보고.
  - 원인: `check_force_condition` 절대값(`3.0 N`)이 `Tool_Weight` 오차·감속 노이즈에 조기 반응 → 허공 `baseline_fz` 차감(`abs(fz - baseline_fz) >= 4.0 N`) + `0.05 s` 안정화로 교체.
  - 이후 **13:55:03 ~ 14:04:16** 사이 7회 연속 빌드하며 사용자가 `READY_OFFSET=-95.0`, `TOUCH_STEP_Z=-1.0`, `DRAW_FORCE_Z=-3.0` 직접 튜닝.
- **2026-11-14 14:05:31 ~ 14:11:17** (`e109e205` #14~#16) 사용자 파일 선확인 원칙 합의 → 5 mm 분할 재접근 실패 → 연속 힘 제어 하강 전환
  - `14:05:31`: 수정 전 사용자 튜닝 파라미터 선확인 지시.
  - `14:05:39`: 그리는 중 펜촉 이격 문제 → `ensure_contact()`, `draw_segment()`(`5.0 mm` 분할, `MIN_CONTACT_FORCE=2.0 N`, `-0.5 mm` 재접근) 도입(`14:07:00` 빌드).
  - `14:11:17`: 5 mm 분할 병목으로 극도로 느리고 여전히 이격됨 → 단계 하강 폐기, **연속 힘 제어 하강 `wait_paper_contact()`** 도입(`COMPLIANCE_STX[2]` `800 → 400.0`, `DRAW_FORCE_Z=-12.0 N`, `TOUCH_FORCE_THRESHOLD=5.0 N`, 변당 단일 `movel`).
  - 이후 **14:12:29 ~ 14:17:36** 6회 빌드하며 `-12`, `-10`, `-4`, `-5 N` 및 `TOUCH_TIMEOUT=10.0` 실기 비교.
- **2026-11-14 14:18:24 ~ 14:21:24** (`e109e205` #17~#19) 정지마찰 불감대 규명 및 `DR_FC_MOD_ABS` `+Z` 들림 버그 수정
  - 실측 현상: `-12/-10 N`은 과도하게 강하고 `-4/-5 N`은 M0609 정지마찰 불감대 때문에 하강 자체가 정지함.
  - 시도 및 버그: 2단계 힘 분리(`-10.0 N` 하강 → `DR_FC_MOD_ABS` `baseline_fz + (-5.0)`) 적용 시, 허공 `baseline_fz=+3.46 N` 기준 목표가 `-1.54 N`으로 들어가 로봇이 `+8.70 N → -1.54 N`으로 힘을 빼려 **`+Z`로 공중 부양**하는 버그를 실기 로그로 규명(`Fz=6.54~6.70 N` 안정 하강 → `8.70 N` 접촉 → 그리기 중 `1.98~3.12 N` 급락).
  - 수정: `DR_FC_MOD_ABS` 제거, 단일 `DR_FC_MOD_REL` 유지(`DRAW_FORCE_Z=-8.0 N`, `TOUCH_FORCE_THRESHOLD=4.0 N`). 이후 **14:22:04 ~ 14:28:13** 7회 빌드.
- **2026-11-14 14:29:22 ~ 14:36:15** (`e109e205` #20~#25) **`moving_baseline` 초미세 접촉 감지 도입 및 감속 관성 영점 오염 해결**
  - 핵심 발견: 앞선 로그에서 등속 하강 구간 `Fz`가 `6.56 ± 0.05 N`으로 극도로 일정하다가 접촉 순간 상승함 → **등속 하강 중 기준값 `moving_baseline`** 도입(`TOUCH_SETTLE_TIME=0.5 s`, 5샘플 평균, `TOUCH_FORCE_THRESHOLD=0.8 N`, `TOUCH_CONFIRM_COUNT=2`, `DRAW_FORCE_Z=-7.5 N`).
  - `14:33:11 ~ 14:33:30`: 펜이 오히려 위로 올라가는 현상(`Fz=1.71 → 1.63 N`) 로그 진단 → `movel(ready)` `-85 mm` 급감속 직후 대기 없이 `set_desired_force(..., DR_FC_MOD_REL)`를 호출해 `+Z` 감속 관성이 영점으로 박힌 것이 원인 → `task_compliance_ctrl()` 직후 **`time.sleep(0.5)`** 추가.
  - `14:36:15`: 공중 조기 감지 방지 → 양방향 `abs(delta_fz)`에서 단방향 `delta_fz >= force_threshold`(`+Z` 반력만 감지)로 전환, `TOUCH_SETTLE_TIME=0.8 s`, `TOUCH_FORCE_THRESHOLD=1.5 N`, `TOUCH_CONFIRM_COUNT=3`.
- **2026-11-14 14:39:28 ~ 14:49:59** (`e109e205` #26~#29) 정지마찰 임계 재확인(`-5.5/-6.0/-5.0 N` 정체 → `-8.0 → -9.0 N` 상향, `TOUCH_TIMEOUT=30.0`, `READY_OFFSET=-93 → -88 mm`, 총 10회 빌드).

### 14:52 ~ 16:08: 그리퍼 J6 회전 정렬, 곡선 일반화, SVG 파서 및 최소 하강 힘 자동 탐색

- **2026-11-14 14:52:12 ~ 14:56:21** (`e109e205` #30~#34) 2지 그리퍼 방향 정렬 및 곡선 일반화(`draw_stroke`)
  - 사용자 아이디어: 2지 평행 그리퍼의 손가락 수직 방향 이동 시 펜 흔들림 방지를 위해 선 진행 방향에 맞춰 J6 회전 정렬.
  - 구현: `align_gripper_to_direction()`, 2지 대칭성 활용 최단 ±90° 회전, `J6_LIMIT_DEG=180.0`, `CORNER_LIFT_Z=8.0`, `CORNER_ANGLE_THRESHOLD=25.0°`, `DRAW_MODE` (`"circle"`/`"square"`, `CIRCLE_RADIUS=25.0`, `CIRCLE_STEPS=36`), `draw_stroke(segments)`(곡선 연속 회전 + 꼭짓점 리프트 회전). 이후 3회 빌드하며 사용자가 `CORNER_LIFT_Z=3.0`, `DRAW_FORCE_Z=-8.0` 튜닝.
- **2026-11-14 15:03:33 ~ 15:05:25** (`e109e205` #35~#36) **`sample_drawing.svg` 생성 및 SVG 멀티 스트로크 파서 구현**
  - 생성 파일: `ws_dsr/src/rokey1/rokey1/sample_drawing.svg` (`15:05:25`, 611 bytes, `100×100 mm` — 집 본체 사각형 + 지붕 직선 + 해 원 + 3차 베지어 물결 언덕 4요소).
  - 구현: `rokey1/setup.py` `package_data={'rokey1': ['*.svg']}` 등록; `drawingtest1.py`에 `DRAW_MODE="svg"`, `DRAW_AREA_SIZE_MM=80.0`, `CURVE_STEP_MM=3.0`, `STROKE_LIFT_Z=8.0`, `_sample_cubic()`, `_parse_svg_path()`(`M/L/H/V/C/Q/Z`), `load_svg_strokes()`(Y축 반전·중심 정렬) 추가.
  - 빌드 (`15:06:28 ~ 15:16:13`): 5회 빌드(`15:12:42` 1.55초 만에 `SIGINT` 중단 1건 포함), 사용자가 `CIRCLE_STEPS=72`, `J6_LIMIT_DEG=360.0` 확장.
- **2026-11-14 15:30:19 ~ 15:45:02** (`e109e205` #37~#44) 편심·마찰 진단 및 최소 하강 힘 자동 탐색(`calibrate_min_descent_force`)
  - 실기 SVG 드로잉에서 발견된 3가지 물리 문제: ① 펜촉 중심축 정렬 난이도, ② 마찰에 의한 펜촉 미세 이동, ③ J6 회전 시 편심으로 인한 선 불연속.
  - 조치 (`15:36:05`): 비전 미사용으로 **`ALIGN_GRIPPER = False`** 비활성화 + 시작 시 `-5.0 N`부터 `-1.0 N`씩 최대 `-14.0 N`까지 `dz >= 1.0 mm` 하강하는 최소 힘을 자동 탐색하는 `calibrate_min_descent_force()` 구현.
  - 조치 (`15:41:16 ~ 15:42:40`): 초기 순응 예압(`DRAW_PRELOAD_Z=-1.5 mm`, `~0.6 N`) 대신 "종이에서 펜촉이 절대 떨어지면 안 됨" 요구에 따라 자동 탐색된 `touch_force_z`를 `release_force()` 없이 그리기 내내 유지하도록 확정.
  - `15:44:50 ~ 15:45:02`: 회전 사라짐 확인(`ALIGN_GRIPPER = False` 때문임을 안내).
- **2026-11-14 15:45:34 ~ 16:08:39** `[빌드]` 사용자 단독 8회 추가 빌드·튜닝 — 최종 보존본(`collaborate1/experiments/drawingtest_force.py`) 기준 `READY_OFFSET=-85`, `CORNER_LIFT_Z=1.0`, `STROKE_LIFT_Z=1.0`, `DRAW_VEL/ACC=50/50`, `TOUCH_VEL/ACC=15/15` 확정.

### 16:34 ~ 17:24: 붓펜 보호용 저속 단계 접촉(`drawingtest_ryu.py`), `pen_test` 패키지 및 `Fz` CSV 실측

- **2026-11-14 16:34:17 ~ 16:57:57** `[빌드/파일]` **`rokey1/drawingtest_ryu.py` 도입** (후일 `collaborate1/experiments/drawingtest_slow.py`)
  - 목적: 붓펜 보호를 위해 힘·순응 제어를 완전히 배제하고 **저속 위치 제어(`movel`) + 정지 상태 `Fz` 샘플링**으로 안전 접촉 탐색.
  - 핵심 수치: `TOUCH_VEL/ACC=2/2`, `DRAW_VEL/ACC=10/10`, `ENABLE_DRAWING=False`, `CONTACT_STEP_MM=0.2 mm`, `CONTACT_MAX_TRAVEL_MM=1.0 mm`, `CONTACT_FORCE_DELTA_N=0.5 N`, `CONTACT_HARD_LIMIT_N=1.0 N`, `CONTACT_CONFIRM_COUNT=2`, `BASELINE_SAMPLES=12`, `SAMPLE_INTERVAL_S=0.05 s`, `CONTACT_RETRACT_MM=2.0 mm`, 사전 노이즈 가드(`p2p >= 0.25 N` 시 즉시 중단).
  - `16:36:49` `drawing_ryu` 엔트리포인트 등록, `16:57:34` 최초 `--packages-select rokey1` 선택 빌드, `16:57:57` 실기 실행(`.pyc` 생성).
- **2026-11-14 17:10:40 ~ 17:13:25** `[빌드/파일]` **`pen_test` 패키지 신설 및 `force_test_fz.csv` 정지 노이즈 실측**
  - `17:10:40`: 신규 패키지 `pen_test`(`force_test.py`) 최초 빌드(37패키지).
  - `17:12:40`: `--packages-select pentest/` 오타로 0개 빌드 → `17:12:55` 전체 재빌드 성공.
  - `17:13:25`: **`/home/qownsdud/force_test_fz.csv`**(716 bytes, 50샘플, `0.000 ~ 9.800 s`, 5 Hz) 기록 완료.
  - 정밀 통계: 평균 **`3.8123 N`**, 표준편차 `0.0389 N`, 최소 `3.7358 N`(`6.6 s`), 최대 `3.8749 N`(`1.8 s`), **Peak-to-Peak `0.1391 N`** (전반 `0~5.2 s` 평균 `3.8445 N` → 후반 `5.4~9.8 s` `3.7744 N`, `-0.07 N` 미세 드리프트). 기준값 차감 시 `0.5 N`급 접촉 감지가 충분히 가능함을 입증.
- **2026-11-14 17:21:57 ~ 17:24:03** `[빌드/파일]` **`contact_test` 추가 및 `pen_contact_manual.csv` 수동 접촉 실측**
  - `17:21:57`: `--packages-select pentest` 오타로 0개 빌드 → `17:22:08` `--packages-select pen_test` 성공(`contact_test`, `force_test` 등록).
  - `17:24:03`: **`/home/qownsdud/pen_contact_manual.csv`**(5,750 bytes, 250샘플, `0.001 ~ 24.803 s`, 10 Hz — 5초 `baseline` + 20초 `observe`) 기록 완료.
  - 구간별 정밀 수치:
    - `baseline`(`0.001 ~ 4.901 s`, 50샘플): 평균 **`3.6770 N`**, 표준편차 `0.0320 N`, Peak-to-Peak **`0.1189 N`**
    - 비접촉 대기(`4.903 ~ 12.904 s`): 평균 `3.5817 N`
    - 1차 접촉(`13.003 ~ 14.404 s`): `3.2537 → -1.1757 N`(`13.604 s`, `ΔFz ≈ -4.85 N`) 후 `+0.68 N` 완화
    - 강한 압입(`14.504 ~ 16.703 s`): 최대 음압 피크 **`-36.8247 N`**(`16.603 s`, `ΔFz ≈ -40.50 N`)
    - 해제/후퇴(`16.803 ~ 18.304 s`): `-33.11 → +2.92 N` 급속 복귀
    - 히스테리시스 안정화(`18.403 ~ 23.103 s`): `2.99 → 3.51 N` (해제 직후 약 `0.6~0.7 N` 잔류, 약 5초 후 해소) → 최종 복원(`23.204 ~ 24.803 s`): `3.64 ~ 3.82 N` 복귀.

### 2026-11-15: 팀원 오프라인 개발 구간

- 본 개발 PC에서는 대화 및 `ws_dsr` 빌드가 0건이었음.
- 같은 날 팀원 장태원(`jtw`/`TW-94-git`)이 오프라인에서 A4 경로 계획 및 4×4 3펜 배정(245 strokes, `15,021 → 5,166점`)을 개발했으며, 해당 기록은 다음 날 `12:00:51` 커밋 `b0e00eb`의 `docs/WORK_STATUS.md`에 반영됨.

---

## 4장. 멀티펜·캘리브레이션·필기체·이미지 벡터화 및 팀원 병렬 협업 본격화 (2026-11-16)

*(당일 `ws_dsr`에서 총 **62회** `colcon build` 수행, 대화 `842be4dd` 전반부 74개 요청 + 팀원 `RyuM-S`·`jtw`/`TW-94-git`·`qownsdud`(`yongsoo`/`bae`/`main`) 다중 브랜치 병렬 개발 진행.)*

### 09:50 ~ 12:31: `collaborate1` 정리, GitHub `A4` 다중 브랜치 분기, `RyuM-S` `pentest` 통합 및 `qt_hmi` 구성

- **2026-11-16 09:50:04** `[파일]` `ws_dsr/src/collaborate1` 패키지 기본 설정(`setup.cfg`, `resource/collaborate1`, `test/*`) 생성·갱신.
- **2026-11-16 09:54:09 ~ 09:59:56** (`842be4dd` #1~#3) `drawingtest1.py` vs `drawingtest_ryu.py` 비교 및 파일명 정비
  - `09:54:09` / `09:54:19`(중복 전송): 두 코드의 차이 분석 요청 → 순응+힘 제어 `moving_baseline`(`TOUCH_VEL=15`, `DRAW_VEL=50`) vs 붓펜 보호용 0.2 mm 단계 위치 제어·정지 샘플링(`TOUCH_VEL=2`, `DRAW_VEL=10`, `ENABLE_DRAWING=False`) 대조 보고.
  - `09:59:07 ~ 09:59:56`: `drawingtest1.py` → `drawingtest_force.py`, `drawingtest_ryu.py` → `drawingtest_slow.py`로 이름 변경 및 `collaborate1/setup.py` `console_scripts` 갱신(`py_compile` 통과).
- **2026-11-16 10:12:56 ~ 10:20:50** (`842be4dd` #4~#8) + `[Git]` `ws_dsr/src` GitHub `main` 최초 force push (`86d9e7a`)
  - `10:12:56 ~ 10:16:01`: `ws_dsr` GitHub 공유 요청(`build/` 575 MB, `install/` 555 MB, `log/` 1.3 GB 제외 권고, `src/.gitignore` 작성).
  - `10:18:33 ~ 10:19:08`: 원격 `main`의 기존 초기 커밋 `a8c6e4b` 의미 질의("커밋이 뭔데?") 및 빈 메시지 재확인.
  - `10:19:52 ~ 10:20:50`: 덮어쓰기(2번) 선택 → 커밋 **`86d9e7a`** (`10:20:24`, `qownsdud`, `Upload ws_dsr workspace src`, 1,489개 파일, +277,218줄)로 `main` force push (`vecow_ecx2000.stl` 54.21 MB 경고 발생했으나 정상 푸시).
- **2026-11-16 10:29:34 ~ 10:32:56** (`842be4dd` #9~#11) + `[Git]` 코드 연혁 추가 및 루트 `README.md` 반영
  - 커밋 **`aff163b`** (`10:30:22`, `Add code history to src/README.md`, +18줄).
  - `10:31:25`: 메인 화면 하단 미표시 원인(`src/README.md` 위치) 확인 후 루트 `/README.md` 복사 → 커밋 **`7e73179`** (`10:32:42`, `Add README.md to repository root`, +259줄).
- **2026-11-16 10:43:03** `[Git]` 팀원 `RyuM-S` (`origin/ryu`) 커밋 **`96631e4`** (`Add pentest package`, 17개 파일, +1,947줄)
  - 추가 스크립트 9종: `draw_line.py`, `draw_path.py`, `draw_square.py`, `force_compare.py`, `force_control_test.py`, `force_test.py`, `manual_move.py`(0B 빈 파일), `move_test.py`, `pendant_force_monitor.py`. (당시 `pentest/setup.py`에 `force_control_test.py` 오타와 `force_compare` 누락 포함.)
- **2026-11-16 10:47:00 ~ 10:50:33** (`842be4dd` #12~#13) `ryu` 브랜치 `pentest` 9개 스크립트를 `collaborate1`로 복사 및 4단계 폴더 정리 방안 논의.
- **2026-11-16 10:53:16 ~ 11:07:28** `[파일]` 별도 GUI 패키지 `/home/qownsdud/ws_cobot_pjt/qt_hmi` 생성
  - 구성: `package.xml`(maintainer `BL`), `setup.py`(`hmi_main`), `cobot1_hmi.ui`(22,422 bytes, Qt Designer), `hmi_gui.py`(PyQt5 6축 슬라이더 `-180~180°`, Start/Pause/Resume/E-Stop, Home/Pick/Place 포즈 버튼), `hmi_main.py`, `emergency_switch.jpeg`, `hmi_ros2.py`(`hmi_gui_node`, `/dsr01/joint_states`·`/dsr01/state`·`move_joint`·`/dsr01/stop` 연동).
- **2026-11-16 11:06 ~ 11:11:58** (`842be4dd` #14) 사용자 수동 백업 `src/collaborate1_codeback/`(13개 파일) 이동으로 빈 `collaborate1` 폴더 복원 + `pentest` 통합 + 호환성 일괄 수정
  - 조치: `sample_drawing.svg` 복사, `package.xml`에 `rclpy`/`dsr_msgs2` 추가, `setup.py`에 `*.svg` `package_data` 추가 및 오타(`grip_test` → `grip_text`, `force_control_test.py` → `force_control_test`, 누락된 `force_compare` 추가, 빈 `manual_move` 제외) 수정 후 `colcon build` 성공(`11:11:52`).
- **2026-11-16 11:14:36 ~ 11:21:20** (`842be4dd` #15~#20) VS Code Pylance `dsr_msgs2.srv` 밑줄 및 `super`/`RuntimeError` 내장함수 미정의 오류 해결
  - 조치: `ws_dsr/.vscode/settings.json`, `ws_dsr/pyrightconfig.json`, 상위 루트 `ws_cobot_pjt/.vscode/settings.json`에 `install/*/site-packages` 경로와 `"python.defaultInterpreterPath": "/usr/bin/python3"`(Python 3.12.3) 추가.
- **2026-11-16 11:52:31** `[파일]` 사용자가 `draw_line.py` 14행에 `# current force를 matplotlib로 확인해보기 홀더만들기 vector` 메모 주석 추가.
- **2026-11-16 11:53:07 ~ 11:55:02** (`842be4dd` #21~#22) + `[Git]` 커밋 **`1acf396`** (`11:53:32`, `Merge pentest scripts into collaborate1 and sync ws_dsr/src`, 25개 파일, +4,653줄) `main` 푸시. 직후 사용자가 "`main`에는 최종 코드만 등록하겠다"는 브랜치 분리 원칙 명시.
- **2026-11-16 11:56:22 ~ 12:00:05** (`a73748f9` 재개) + `[Git]` **`rokey_collaborate_1` 기반 `main` 원복 (`b1bcf16`)**
  - `rokey_collaborate_1/README.md`(파일 트리, 연혁, 기술 스택) 작성 후 커밋 **`b1bcf16`** (`11:57:22`, `docs: add README.md with file tree, chronology, and tech stack`, 부모 `a8c6e4b`).
  - `origin/main`이 `ws_dsr` 히스토리로 덮여 있음을 확인한 뒤 사용자 선택(A1)으로 `git push --force-with-lease origin main` 수행하여 `main`을 초기 A4 구조로 복원.
- **2026-11-16 12:00:51** `[Git]` 팀원 `jtw` (`jang` 브랜치) 커밋 **`b0e00eb`** (`Replace jang contents with A4 workspace snapshot`, 1,590개 파일)
  - 내용: `phase1_kiosk`, `phase2_lib_lineart`, `phase3_path_planner`(`drawing_plan.py`, `test_drawing_plan.py`), `phase4_pyqt_gui/main.py`, `qt_hmi/`, `docs/WORK_STATUS.md`(11/15 장태원 개발 기록) 스냅샷 업로드.
- **2026-11-16 12:06:12 ~ 12:09:09** (`842be4dd` #23~#26) + `[Git]` **`bae` 브랜치 독립 창설 (`efec07b`)**
  - 사용자가 `bae` 브랜치 생성 후 업로드 요청 → 임시 커밋 `25a3964`(`12:07`, `main` 파일 혼재) 확인 후 orphan 클린 커밋 **`efec07b`** (`12:08:46`, `Upload ws_dsr/src to bae branch`, 1,513개 파일, +282,147줄)로 `bae` 브랜치 단독 구성 완료.
- **2026-11-16 12:31:55** `[Git]` 팀원 `TW-94-git` (`jang`) 커밋 **`c6c8bf2`** (`Merge remote-tracking branch 'origin/jang' into jang`).

### 14:25 ~ 16:05: 측면 막대기 높이 탐색(`draw1.py`), 다중 루트(`draw_routes.py`), 52자 단선 필기체(`cursive_font.py`) 및 `TW-94-git` 3색 경로 최적화

- **2026-11-16 14:25:54 ~ 14:37:52** (`842be4dd` #27~#31) **측면 기준 막대기 접촉 높이 탐색 `draw1.py` 개발 및 공중 오판 해결**
  - `14:25:54`: 붓펜 옆 막대기가 바닥에 닿을 때 외력으로 정지 → 살짝 상승해 붓펜으로 부드럽게 그리는 `draw1.py` 작성(`PROBE_STEP_MM=0.2`, `PROBE_VEL=5`, `CONTACT_FORCE_DELTA_N=1.0 N`, `LIFT_AFTER_STICK_MM=1.5 mm`, `DRAW_VEL=15`).
  - `14:34:24 ~ 14:35:27`: 공중 정지 로그(`Baseline Fz=3.142 N`, 하강 `0.20 mm`·`0.40 mm`에서 `deltaFz=+1.547/+1.516 N` → 공중 `Z=388.81 mm` 오판) 규명 — 첫 `movel` 하강 관절 마찰/토크 오프셋(`+1.5 N`)이 원인 → `WARMUP_STEPS=2`(0.4 mm 워밍업 후 `probe_baseline` 재설정), `SETTLE_TIME_S=0.12 s`, `READ_SAMPLES=3` 평균, `draw_baseline` 분리 적용.
  - `14:37:41`: 추가 공중 정지 방지를 위해 `CONTACT_FORCE_DELTA_N` `1.0 → 2.5 N`, `HARD_LIMIT_FORCE_N` `5.0 → 8.0 N` 상향.
  - **14:39:40 ~ 14:55:25** `[빌드]` 8회 반복 실기 튜닝 — 사용자가 직접 `L_VEL/ACC=50/50`, `READY_OFFSET=-90.0`, `PROBE_STEP_MM=0.5`, `PROBE_MAX_TRAVEL_MM=20.0`, `HARD_LIMIT_FORCE_N=30.0`, `LIFT_AFTER_STICK_MM=2.0` 확정.
- **2026-11-16 14:52:29 ~ 15:00:31** `[Git]` 팀원 `TW-94-git` (`jang`) 커밋 3건
  - **`66c3956`** (`14:52:29`, `feat: optimize A4 drawing paths with 3-color grouping`, +12,620줄: `path_optimizer.py` 252줄, `optimize_existing.py`, `test_path_optimizer.py`, `latest_lineart_drawing_plan_optimized.json`).
  - **`2878143`** (`14:56:49`, 구 `main.py.*.bak` 삭제).
  - **`fb5d063`** (`15:00:31`, `README` 갱신).
- **2026-11-16 14:56:06 ~ 14:59:10** (`842be4dd` #32~#33) 과압 감지(`HARD_LIMIT_FORCE_N`) 역할 설명 및 5 mm 10분할 동기 `movel`로 인한 직선 중간 멈춤 제거(변당 단일 `movel` 연속 이동).
- **2026-11-16 15:01:29 ~ 15:20:24** (`842be4dd` #34~#39) **`draw_routes.py`, "+2 mm 굵은 선 / +3 mm 얇은 선" 발견 및 곡선/직선 명령 분리**
  - `15:01:29 ~ 15:07:38`: 사인파·지그재그·나선·별 다중 루트 `draw_routes.py` 신설 → 타 파일 파라미터 참조 실수 지적 후 `draw1.py` 사용자 확정 파라미터 100% 유지해 재작성(오프라인 빌드 3회로 속도 튜닝).
  - `15:17:36`: 사용자 실측 발견 **"+2 mm 들면 굵은 선, +3 mm 들면 얇은 선"** → `THICK_LIFT_MM=2.0`, `THIN_LIFT_MM=3.0` 도입.
  - `15:19:52`: 직선에서 `movesx` 사용 시 꼭짓점이 둥글게 휘는 문제 지적 → 곡선(`movesx`: 사인파·나선)과 직선(`movel`: 지그재그·별) 분리 적용.
- **2026-11-16 15:34:57 ~ 16:05:26** (`842be4dd` #40~#41) **52자 3D 단선 필기체 `cursive_font.py` & `draw_cursive.py` 구현**
  - `15:34:57 ~ 15:36:40`: `cursive_font.py`(13,470 bytes, 대·소문자 52자 제어점 + Catmull-Rom 보간 + 인접 소문자 연결 + 진행 방향 `dy` 기반 Downstroke `+2.0 mm` ~ Upstroke `+3.0 mm` 연속 Z 변화) 및 `draw_cursive.py`(3D `movesx` + 직선 보조획, 기본 `"Hello"`, `char_height_mm=16.0`) 작성·검증.
  - `15:40:20`: 속도 개선(`DRAW_VEL` `15 → 45`, `steps_per_seg=2`) 후 **15:40:55 ~ 16:05:18** 7회 오프라인 빌드·튜닝(사용자 메모 `# 글을 쓰는 중에 멈추지 않도록 등속설정 무브b`, `DRAW_VEL/ACC=500/500` 실험).

### 16:10 ~ 19:06: 9점 바닥 평면 캘리브레이션 실측, 펜·막대 티칭, 1~14단계 통합 아키텍처 및 `run_logs` 3회 검증

- **2026-11-16 16:10:38 ~ 16:23:27** (`842be4dd` #42~#47) **`calibrate_plane.py` 구현 및 PC 키보드 조그·외력 표시 내장**
  - 최소자승법 9점 평면 피팅(`z = a*x + b*y + c`, `~/.ros/plane_calibration.json`) 작성 → Auto 모드 중 티치 펜던트 제어권 충돌 해결을 위해 PC 키보드 조그(`w/s/a/d/e/c`, 자유 `step_mm`, `g/f/n` DO1·2 그리퍼, `o` 기록) 및 실시간 `Fz`/`deltaFz` 출력 추가.
- **2026-11-16 16:23:44 ~ 16:37:17** `[Git]` 팀원 `TW-94-git` (`jang`) 커밋 4건: **`a7246ce`**(`run_full_pipeline.py` 통합 스크립트), **`fab338f`**(정리 A4 백업), **`9946a30`**(병합), **`41257c7`**(`.gitignore`).
- **2026-11-16 16:54:47 ~ 16:57:29** (`842be4dd` #48~#49) **실물 작업대 9점 바닥 캘리브레이션 최초 실측 완료!**
  - 저장 경로: `/home/qownsdud/.ros/plane_calibration.json` (당시 플랜지 `TCP Z=0` 기준)
  - 평면 방정식: `z = (+0.002184) * x + (-0.000099) * y + (+237.340)`
  - 기울기·정밀도: X축 `+0.125°`, Y축 `-0.006°`, 총 기울기 `0.125°`, **평탄도(P-V) `0.533 mm`**, **평면 RMSE `0.189 mm`**
  - 측정 범위: `X: 234.84 ~ 477.34 mm` (`242 mm`), `Y: -161.32 ~ +176.68 mm` (`338 mm`), `Z: 237.637 ~ 238.622 mm`
  - 즉시 `draw_cursive.py`, `draw_routes.py`에 `load_plane_slope()` 기울기 Z 보정 연동 완료.
- **2026-11-16 16:59:23 ~ 16:59:49** (`842be4dd` #50) 순수 PC 키보드 수동 조종 노드 `manual_move.py` 구현(`w/s/a/d/e/c`, `vel`, `g/f/n`, `p`, `fz`, `home`).
- **2026-11-16 17:01:54** `[Git]` `qownsdud` (`origin/yongsoo`) 커밋 **`4decdd9`** (`노트북 A4 작업 내용 반영`, 94개 파일, +22,978 / -67,608줄)
  - 핵심: 신규 ROS 2 패키지 3종(`art_interfaces`, `art_job_manager`, `art_kiosk_bridge`), 키오스크 관리자 HMI(`hmi_api.py`, `admin.html`, `admin.js`), `TEAM_CONTRACT_V1.md`·`README_REAL_JobManager.md` 및 단위/통합 테스트 스위트 도입.
- **2026-11-16 17:07:08** `[Git]` 팀원 `TW-94-git` (`jang`) 커밋 **`adbcd6c`** (`README` 갱신).
- **2026-11-16 17:22:06 ~ 17:43:53** (`842be4dd` #51~#52) **`teach_pen_slots.py` 및 `pen_pick_place.py` 분리 구현 + 펜 3개 실물 티칭 완료**
  - 펜 3개 위치 티칭(`teach_pen_slots.py`)과 자동 픽앤플레이스(`pen_pick_place.py`, 초기 `APPROACH_OFFSET_Z=50.0 mm`) 분리.
  - 실측 저장(`~/.ros/pen_slots.json`): 펜 1 `[567.362, 42.678, 366.732, ...]`, 펜 2 `[568.267, 11.279, 366.716, ...]`, 펜 3 `[568.259, -19.422, 366.728, ...]` (평균 Z `366.725 mm`).
- **2026-11-16 17:50:29 ~ 18:30:26** `[Git]` 팀원 `TW-94-git` (`origin/jang`) 커밋 5건 — **실측 9점 좌표 56분 만에 실시간 연동!**
  - **`3a82590`** (`17:50:29`, 39개 파일 +125,072줄): `qownsdud`가 `16:54:47`에 측정한 9점 캘리브레이션 좌표를 `paper_coordinates.py`(`ROBOT_PAPER_POINTS`, `242×337 mm`)와 `robot_coordinate_transform.py`에 즉시 반영, 품질 검증·시뮬레이션 GIF 2종 추가.
  - **`f535afb`** (`17:52:37`, SSH 키·자격증명 보호 `.gitignore`), **`24b027b`** (`18:04:27`) & **`13a0348`** (`18:15:34`, `center` 좌표 보정), **`a7eccd7`** (`18:30:26`, `origin/jang` 1일차 완료, `update_paper_size.py`·통합 테스트).
- **2026-11-16 17:59:14 ~ 18:01:31** (`842be4dd` #53~#54) `pen_pick_place.py` 접근 높이 `APPROACH_OFFSET_Z` `50.0 → 100.0 mm` 상향.
- **2026-11-16 18:17:18 ~ 18:44:45** (`842be4dd` #55~#60) **기준 막대 분리형 1~14단계 멀티펜 아키텍처 확정 (`draw_multi_pen.py`)**
  - `18:17:18`: 펜 옆 고정 막대 방식을 폐기하고, 별도 거치대의 **기준 막대 집기 → 포스 높이 측정 → 반납 → 펜 1·2·3 순차 집기·그리기·반납 → 홈 복귀**의 1~14단계 확정.
  - `18:18:17 ~ 18:23:41`: `teach_stick_slot.py` 구현·실측 후 `stick_slot.json` Z를 펜 평균 `366.725 mm`로 통일(`389.737 → 366.725 mm`).
  - `18:24:02 ~ 18:42:09`: `draw_multi_pen.py`(펜 1 정사각형, 펜 2 정삼각형, 펜 3 원) 구현 및 4회 오프라인 튜닝 — `READY_OFFSET` `-90 → -100.0 mm`, `PEN_Z_OFFSETS` `[2, 2, 2] → [14.0, 14.0, 14.0]`(기준 막대~붓펜 길이 차 실측 반영), `STROKE_LIFT_MM=15.0`, `DRAW_VEL/ACC=25/25`.
  - `18:44:34`: `stick_slot.json` X 좌표 `+2 mm` 보정(`581.354 → 583.354 mm`).
- **2026-11-16 18:45:54 ~ 18:47:57** (`842be4dd` #61) **`run_logger.py` 자동 실행 로그 저장기 구축** — OS FD 1·2 `os.pipe` + `os.dup2` Tee 복제로 `ws_dsr/run_logs/<시작>_<종료>.txt` 자동 저장, 5개 노드 일괄 적용.
- **2026-11-16 18:53:46 ~ 19:06:14** `[실물로그]` `draw_multi_pen` 실물 3회 실행 검증
  - **로그 #1** (`18:53:46 ~ 18:57:16`, 3분 30초): **최초 1~14단계 완전 성공** — 기준 막대 `Baseline Fz=-10.266 N`, 하강 `4.50/5.00 mm`(`+8.73/+17.30 N`) → 바닥 **`Z=317.66 mm`** → 펜 1·2·3 완주.
  - **로그 #2** (`19:02:36 ~ 19:02:39`, 3초): 기준 막대 집기 직전 즉시 중단.
  - **로그 #3** (`19:02:41 ~ 19:06:14`, 3분 33초): **2차 완주 성공** — 바닥 **`Z=317.67 mm`** (직전 대비 **`0.01 mm` 반복 정밀도 입증**).

### 20:06 ~ 21:58: `DrawingPlan v0.2`, `collaborate1` 서브모듈 리팩토링, `image_vectorizer.py` 및 최초 3펜 분할 인물화 실물 완주

- **2026-11-16 20:06:33** `[Git]` `qownsdud` (`origin/yongsoo`) 커밋 **`c3a3e18`** (`DrawingPlan v0.2 계약 및 경로 계획 변경 반영`, 45개 파일, +193,410줄) — `docs/DRAWING_PLAN_V02_KR.md` 신설(`schema_version: "0.2"`, `paper_top_left_x_right_y_down`, `PEN_1~3`, SHA-256 불변성).
- **2026-11-16 20:10:28 ~ 20:39:33** (`842be4dd` #62~#65) + `[Git]` `collaborate1` 4대 서브모듈(`core/`, `setup_tools/`, `app/`, `experiments/`) 개편 + `config/registry.yaml`(20개 노드 자동 등록) + `ws_dsr/src/README.md` 갱신 → 커밋 **`5363941`** (`20:39:29`, `bae`, 32개 파일, +2,629줄).
- **2026-11-16 21:15 ~ 21:28:53** (`842be4dd` #66~#69) **`image_vectorizer.py` 1차 구현 및 `draw_image_multi_pen.py` 작성**
  - `21:15`: 11/13 `16:45:44` 키오스크 확정본(10,942 bytes, `512×724`)을 `test_image/test_image.png`로 배치.
  - `21:16:49 ~ 21:20:21`: 초기 경로 탐색 누락 지적 후 `test_image.png` 직접 확인.
  - `21:21:18 ~ 21:22:20`: `core/image_vectorizer.py` 작성(Zhang-Suen 세선화 → 8-연결 추적 → RDP `1.0 px` → NN 정렬) → **382획, 857점**(`test_image_strokes.json`, `.svg`, `_preview.png`) 생성.
  - `21:26:54 ~ 21:28:03`: `app/draw_image_multi_pen.py` 작성 — 9점 안전 영역(`RECT_MARGIN_MM=20.0`, `X=[254.8~457.3]`, `Y=[-141.3~156.7]`), 3펜 균등 분배(`[128, 126, 128]`획), 획 전환 리프트 `4.0 mm`.
- **2026-11-16 21:29:07 ~ 21:32:15** `[실물로그]` + (`842be4dd` #70) **로그 #4 (`21:29:07`)** `FileNotFoundError`(`install/`에 `test_image_strokes.json` 누락) → `test_image/__init__.py`·`setup.py` `data_files`·`_resolve_image_strokes_file()` 추가로 해결.
- **2026-11-16 21:32:24 ~ 21:54:53** `[실물로그]` **로그 #5 — 최초 3펜 분할 인물화 실물 로봇 드로잉 완주! (22분 29초)**
  - 바닥 측정: `Baseline Fz=-10.517 N` → **`Z=317.66 mm`** (`0.00~0.01 mm` 정밀도 재확인).
  - 실행 내역: 총 382획(857점) — 펜 1(`128획/287점`, 6분 31초) → 펜 2(`126획/285점`, 6분 46초) → 펜 3(`128획/285점`, 6분 50초) 모두 정상 완주 후 홈 복귀.
- **2026-11-16 21:53:39 ~ 21:58:07** (`842be4dd` #71~#74) + `[Git]` `image_vectorizer.py` 품질 2차·3차 대폭 개선 및 `bae` 푸시
  - 실물 완주 직전 프리뷰 품질 피드백 대응: 2차(`2×2` closing, `eps=0.5`, `merge=2.5` → 294획/3,237점) → 3차 전면 개편(`3×3` closing + `prune_spurs(3)` + 분기점 직진 방향 추적 + `chaikin_smooth` + `merge_dist_px=4.0` → **214획, 1,177점**).
  - 커밋 **`8d0a567`** (`21:58:01`, `bae`, `Add image vectorizer, test_image vectors, and draw_image_multi_pen`, 9개 파일, +11,238줄).

---

## 5장. 멀티노트북 FastDDS, `draw_image_standalone`, MediaPipe 하이브리드, 그리고 통합 워크스페이스 `A4` 창설 (2026-11-17)

*(당일 `ws_dsr` 50회 + `A4` 19회 = 총 **69회** `colcon build`, 10개 대화·36회 `drawing_previews`·14개 Git 커밋이 얽힌 프로젝트 최대 전환점.)*

### 09:49 ~ 12:38: FastDDS Discovery Server 진단, `yongsoo` 7패키지 통합, 단일 `art` 패키지, `draw_image_standalone.py` 및 RViz TF 해결

- **2026-11-17 09:49:07 ~ 10:46:41** (`3040210a` #1~#6) **멀티 노트북 FastDDS Discovery Server 트러블슈팅**
  - `09:49:07 ~ 09:50:27`: Notion 가이드의 한글 플레이스홀더(`서버로 설정할 PC의 IP:11811`)가 `~/.bashrc`에 그대로 들어가 `export` 문법 오류 발생 → `RMW_IMPLEMENTATION=rmw_fastrtps_cpp`, `ROS_DISCOVERY_SERVER=172.16.0.92:11811`, `ROS_SUPER_CLIENT=TRUE`, `ROS_DOMAIN_ID=40` 정리.
  - `09:53:48`: 다른 노트북용 `fastdds-discovery.service` 가이드 제공.
  - `10:44:17 ~ 10:46:41`: 다른 노트북 서버(`172.16.0.88:11811`) 통신 불가(`ping` 100% 손실) → `ip neigh show`에서 서버와 게이트웨이(`172.16.0.1`) MAC 주소 동일(`cc:88:c7:c2:71:76`) 확인 → **Wi-Fi AP Isolation(클라이언트 격리)** 판명(`172.24.0.x` 강의실 Wi-Fi 또는 핫스팟 권고).
- **2026-11-17 10:29:56 ~ 10:30:56** (`842be4dd` #75~#76) ROS 2 노드(`console_scripts`)와 공용 모듈(`core/`) 개념 확인.
- **2026-11-17 10:43:33 ~ 10:53:07** `[Git]` `qownsdud` (`origin/yongsoo`) **ROS 2 기능별 7패키지 체제 완성**
  - **`1b81ff6`** (`10:43:33`, 94개 파일, +3,780 / -2,287줄): `art_interfaces`(`PrepareArtwork.action` 추가), `art_kiosk`, `art_kiosk_bridge`, `art_artwork_pipeline`(`bae`의 `cursive_font.py` 2D 채택 + `puzzle/colors.py`), `art_job_manager`, `art_drawing_controller`(안전 거절 경계), `art_bringup` 7개 패키지 통합 및 `docs/ROS2_PACKAGE_REFACTOR_KR.md` 신설.
  - **`9a46f94`** (`10:53:07`, 84개 파일): 구형 `phase1~3` 호환 진입점 제거 및 참고 데이터를 `data/reference/`로 이동.
- **2026-11-17 11:10:01 ~ 11:28:07** (`842be4dd` #77~#81, `e109e205` #45~#47) + `[Git]` `yongsoo` 7패키지 분석 → `ws_dsr/src` 복사(11:20) → **단일 `art` 패키지(68개 파일, 8개 실행 래퍼) 통합**(`11:21~11:22`, `colcon build` 10.1 s 성공) → 커밋 **`2a600dc`** (`11:28:07`, `bae`, `Update workspace src (add art package)`).
- **2026-11-17 11:36:00 ~ 12:19:54** (`e109e205` #48~#64) **단일 독립 실행기 `draw_image_standalone.py` 개발 및 `--virtual` 지원**
  - `11:38:27`: 외부 패키지 없이 `OpenCV`+`NumPy`+`DSR_ROBOT2`만으로 이미지 벡터화→3펜 드로잉을 완결하는 `collaborate1/app/draw_image_standalone.py` 신설 및 `registry.yaml` 등록(`--dry-run`: 102획 `[35, 32, 35]`).
  - `11:41:29`: `SKETCH_MODE`, `merge_close_strokes(1.5 mm)`, 9점 영역 배치(`compute_safe_rect`) 설명 및 반영.
  - `11:46:00 ~ 12:05:33`: **빈 닫힌 그리퍼 9점 자동 재측정(`calibrate_9pt_with_closed_gripper`, `AUTO_CALIBRATE_9PT=True`)** 구현(오타 `"0점"` → `"9점"` 정정) 및 무게추 회피 여백 `CALIBRATE_INSET_MM=20.0 mm` 추가.
  - `12:10:03`: `ros2_control_node` Overrun 경고(`169 ms`, `missed cycles: 17`)가 정상 활성화 중 일시 지연 `WARN`임을 확인.
  - `12:11:55 ~ 12:17:50`: `sodvir` 실행 시 `set_tool`/`set_tcp` 대기 정지 → `--virtual` 옵션 추가(`set_tool`/`set_tcp` 및 포스 탐색 생략). 실행 시 화살표 키 오입력(`[B`)으로 일반 모드 진입한 해프닝 정정.
- **2026-11-17 11:53:56 ~ 11:54:29** (`842be4dd` #82) + `[Git]` `~/.ros/{pen_slots, plane_calibration, stick_slot}.json` 3종을 `bae` 브랜치 루트에 커밋 **`c4fb5d0`** (`11:54:27`, `Add calibration and slot JSON files to bae branch root`) 업로드.
- **2026-11-17 12:25:24 ~ 12:38:15** (`e109e205` #65~#66, `22979593` #1~#5) **RViz `No tf data` / `Waiting for robot_description` 근본 원인 규명 및 해결**
  - 원인: 오전 FastDDS 설정 과정에서 `~/.bashrc`에 남은 `ROS_DISCOVERY_SERVER=172.24.1.204:11811` 및 `ROS_SUPER_CLIENT=TRUE`가 미연결 외부 서버만 바라보며 **로컬 PC 내부 ROS 2 통신(`/robot_description`, `/tf`)까지 전면 차단**함.
  - 해결 (`12:38:15`): `~/.bashrc`의 FastDDS 4줄 전면 `#` 주석 처리 + `unset`으로 즉시 정상 복구. (`e109e205` #67에서 `17:01:23` 해결 완료 보고.)

### 12:46 ~ 16:57: 실물 3펜 완주(214획), `AGENTS.md` 도입, 막대 충돌 해결·`draw_height_test`·`movesx` 하이브리드·키오스크 A4 가로 2 cm 여백 개편

- **2026-11-17 12:46:46 ~ 13:09:15** `[실물로그]` **로그 #6 (`run_logs/20261117_124646_20261117_130915.txt`)** — 개선된 214획 3펜 분할 인물화 실물 완주(22분 29초, 분배 `[56, 69, 89]`획, 바닥 `Z=317.66 mm`).
- **2026-11-17 12:48:11 ~ 12:54:59** `[Git]` `qownsdud` (`origin/yongsoo`) 커밋 2건
  - **`7cb4d6e`** (`12:48:11`, 28개 파일, +1,622줄): `art_kiosk/workflow.py`(358줄) 신설, 사용자 자동 드로잉·관리자 현재 작업 HMI 통합 및 `docs/HMI_MANUAL_TEST_KR.md` 신설.
  - **`a9ff062`** (`12:54:59`, 12개 파일): **저장소 작업 지침 `AGENTS.md` 최초 도입**(한국어 작성, Markdown 파이프 표 금지 규칙) 및 전체 문서 표 제거 정리.
- **2026-11-17 12:59:45 ~ 14:21:04** (`22979593` #6~#13) **`draw_image_standalone.py` 실전 하드웨어 보완 6연속 개선**
  - `12:59:45`: 기준 막대와 3번 펜 간섭 해결을 위한 **`STICK_GRIP_RZ_OFFSET_DEG = -45.0°`**(Base `+Z` 반시계 45° 회전 파지) + 터미널 단일 키 **`x` 중단 안전 복귀**(`_keyboard_abort_listener`, `held_item` 추적 → 수직 상승 → 원위치 반납 → `HOME_JOINTS`).
  - `13:51:41 ~ 13:54:14`: 바닥 정상 접촉 시 과압 정지 버그(`CONFIRM_COUNT=2` 채우려 추가 `0.5 mm` 하강하다 `30 N` 초과) 수정 → `HARD_LIMIT_FORCE_N` `30 → 60.0 N` 완화 + **2단 정밀 하강(`PROBE_STEP_MM=0.5 mm` → 첫 감지 후 `PROBE_FINE_STEP_MM=0.1 mm`)** 도입.
  - `13:56:56`: 무게추 회피 여백 `CALIBRATE_INSET_MM` `20.0 → 40.0 mm`(4 cm) 확대.
  - `14:13:27`: 시작부 **그리퍼 초기 재정렬(열기 → 닫기)** 추가.
  - `14:16:35 ~ 14:18:30`: `art` 참고 방식 제거 후 검증된 `image_vectorizer.py` 파이프라인 내장 + 매 실행 시 **`ws_dsr/drawing_previews/latest_preview.png` 자동 저장 및 `history/` 자동 아카이브** 구현(`14:18:27`~`20:19:51` 당일 총 **36회** 프리뷰 생성).
- **2026-11-17 15:09:31 ~ 15:55:07** (`22979593` #14~#22) **캘리브레이션 ON/OFF, `draw_height_test.py` / `draw_spell_test.py` 및 `movesx`/`movel` 35° 하이브리드**
  - `15:09:31 ~ 15:14:13`: `--skip-cal`/`--no-cal`/`--cal` 추가(OFF 시 `plane_calibration.json` 저장 기울기 사용, 기준 높이는 기준 막대로 매번 측정).
  - `15:17:32 ~ 15:40:13`: 높이 검증 전용 `draw_height_test.py` 신설(펜 1 정사각형, 펜 2 정삼각형, 펜 3 72분할 원) + `~/.ros/draw_height_test_state.json` 직전 ON/OFF 기억 기능 추가 → 코드에서 `AUTO_CALIBRATE_9PT=False`로 바꿔도 상태 파일이 덮어쓰던 버그를 `code_default` 필드 추가로 수정(`15:40:01`).
  - `15:44:54 ~ 15:47:16`: 꺾임 멈춤 개선 — **`CORNER_ANGLE_DEG = 35.0°` 각도 기반 분할(`split_at_corners`)** 도입(각진 모서리 `≥35°`는 `movel` 정지 보존, 완만 곡선 `<35°`는 최대 80점 단위 `movesx(..., vel_opt=DR_MVS_VEL_CONST)` 연속 주행).
  - `15:55:07`: 사용자가 `draw_height_test.py`를 복제해 `draw_spell_test.py`(6,220 bytes) 생성.
- **2026-11-17 16:04:25 ~ 16:11:28** (`1eeef029` 재개) **`phase1_kiosk` A4 가로 사방 2 cm 여백 개편**
  - `a4_landscape_margin` 기본 고정: `3 px/mm` 기준 **`891 × 630 px`**(`297 × 210 mm`), 사방 `60 px`(`20 mm = 2 cm`) 여백, 중앙 **`771 × 510 px`**(`257 × 170 mm`) 드로잉 영역 + 웹캠 프리뷰 `297:210` 및 점선 가이드·중앙 크롭 연동. `16:11:28` 새 `latest_lineart.png`(121,179 bytes) 확정.
- **2026-11-17 16:08:13 & 16:26:18** `[Git]` `qownsdud` (`origin/yongsoo`) 커밋 2건
  - **`6790803`** (`16:08:13`, 45개 파일, +1,572줄): 획 중간 실시간 일시정지·재개 구현(`ControlDrawing.srv`, `doosan_motion_control.py`, `live_motion.py`, `live_control_server.py`, `docs/CONTINUOUS_PAUSE_RESUME_KR.md`, `docs/ROBOT_TEAM_HANDOFF_KR.md`).
  - **`5a3ecfd`** (`16:26:18`, 9개 파일, +180줄): 중복 ROS 서버 거절 로직 및 로컬 HMI 테스트 격리(`scripts/local_test_env.bash`, `test_duplicate_servers.py`).
- **2026-11-17 16:13:20 ~ 16:57:10** (`22979593` #23~#28) + `[Git]` **`latest_lineart.png` 연결, 벡터화 뭉개짐 해결 및 다중 브랜치 동기화**
  - `16:13:20`: `draw_image_standalone.py` 기본 입력을 `rokey_collaborate_1/phase1_kiosk/confirmed_outputs/latest_lineart.png`로 연결(312획 `[93, 101, 118]`).
  - `16:15:46 ~ 16:17:06`: `rokey_collaborate_1` `files.yaml` 동기화, `ws_dsr`에도 `file_manager.py` 배치 및 `files.yaml`(1,937줄) 생성, `registry.yaml` 갱신.
  - `16:41:36 ~ 16:42:40`: 미리보기 뭉개짐·그물망 선 2대 원인(`3×3 MORPH_CLOSE` 및 `VECTORIZE_MERGE_DIST_PX=4.0`) 제거(`MORPH_CLOSE` 삭제, `MERGE_DIST=0.0`, `EPSILON=0.6`, `MIN_LEN=4.0`)로 원본 형태 깔끔히 복원(`16:42:30` 프리뷰 144,045 bytes).
  - `16:49:59 ~ 16:54:40`: 커밋 **`ae23c52`** (`16:52:42`, `main`, `Update phase1_kiosk and sync files.yaml`), 커밋 **`9140552`** (`16:53:37`, `bae`, `draw_image_standalone`/`draw_height_test`/`draw_spell_test`/`registry`/상태 JSON 동기화), 및 `main`+`bae` 병합 커밋 `7625545` 푸시.

### 17:01 ~ 18:40: MediaPipe 하이브리드(`lineart_mfl_ld.py`) 확정, `sub`/`bae` 정리, `RyuM-S` 캘리그라피, Notion 조사 및 통합 워크스페이스 `A4` 창설

- **2026-11-17 17:03:26 ~ 17:34:11** (`5d83d589` 재개) **MediaPipe Face Landmarker + Canny & LineartDetector 하이브리드(`lineart_mfl_ld.py`) 4단계 개발·확정**
  - `17:03:26`: 팀원의 Haar Cascade 얼굴 ROI `lineart_cv.py` 코드 분석 → MediaPipe Face Landmarker 결합 구상.
  - `17:20:24 ~ 17:22:13`: `mediapipe` 1.x 설치 시 `mp.solutions` 제거로 `controlnet_aux` 충돌 발생 → **`mediapipe==0.10.21`** 다운그레이드 고정(`requirements.txt`), `models/face_landmarker.task`(3.75 MB) 다운로드, **v1**(랜드마크 직접 드로잉) 작성.
  - `17:24:54 ~ 17:26:48`: v1 "가면 느낌" 불만족 피드백 → **v2**(`FACE_LANDMARKS_FACE_OVAL` 폴리곤 마스크 내부 `Canny(22, 65)` + 외부 `LineartConverterDL`).
  - `17:27:25 ~ 17:29:07`: **v3**(머리카락 상단 `0.45`/좌우 `0.15` 타원 ROI 확장) → **v4**(선 두께 차이 해소를 위해 `face_line_thickness=2`, 2×2 `dilate` 적용).
  - `17:29:30 ~ 17:34:11`: 전체 DL vs 하이브리드 비교 후 **`mfl_ld` 최종 확정**(`phase2_lib_lineart/main.py` 기본값 고정, `phase2_lib_lineart/README.md` 신설, 추론 `1.35 s`).
- **2026-11-17 17:35:08 ~ 17:46:44** (`e109e205` #68~#70, `39951373` 재개, `a73748f9` 재개) + `[Git]` 양 워크스페이스 전수 감사 및 `sub`·`bae` 브랜치 업로드
  - `ws_dsr` 감사(`17:35:08 ~ 17:37:08`): `rokey1/setup.py` 죽은 엔트리포인트 3개 제거 및 깨진 `build/pen_test`·`install/pen_test` 심볼릭 링크 정리.
  - `rokey_collaborate_1` 감사(`17:35:24 ~ 17:37:23`): `README.md`·`files.yaml` 동기화, `X/phase2_ai_lineart/` 비정상 잔여 파일 `=0.0.9`, `=1.0.0` 삭제.
  - 커밋 **`6e0ef9e`** (`17:41:10`, `origin/sub`, `Upload rokey_collaborate_1 to sub branch`, 9개 파일: `lineart_mfl_ld.py`, `face_landmarker.task` 등).
  - 커밋 **`82ca6eb`** (`17:46:36`, `bae`, `chore(ws_dsr): organize workspace structure, fix filenames, and sync all ws_dsr files`, 63개 파일: `grip_text.py → grip_test.py` 오타 정정, `archive/`·`tools/`·`calibration_backup/` 정리, `drawing_previews/` 31개·`run_logs/` 6개 동기화).
- **2026-11-17 17:58:49 & 18:01:07** `[Git]` 팀원 `RyuM-S` (`origin/ryu`) 커밋 2건
  - **`4bb08dd`** (`17:58:49`, 51개 파일, +20,212줄): 한글 캘리그라피 모듈 `calligraphy_path_gen.py`·`draw_calligraphy.py`, `diag_move_test.py`, `pentest/pen_height_calibration.py`(663줄) 추가.
  - **`bb49dd9`** (`18:01:07`): 루트 `README.md` 추가.
- **2026-11-17 17:54:52 ~ 18:39:49** (`8b1ba7aa` #1~#7 + 브라우저 서브에이전트 `a47eb03c`) **Notion `10기 A4 퍼즐 드로잉 로봇` 전수 조사 및 통합 워크스페이스 `/home/qownsdud/ws_cobot_pjt/A4` 공식 창설!**
  - `17:56:17 ~ 18:05:10`: 브라우저 로그인 후 메인 페이지와 하위 **11개 페이지 전체** 판독(7개 ROS 2 패키지 아키텍처, 소프트웨어 통합 108테스트 통과·실물 연결 미완료 현황 확인).
  - `18:31:56 ~ 18:39:49`: `rokey_collaborate_1`과 `ws_dsr`을 Notion 구조 기준으로 취합 후 `/home/qownsdud/ws_cobot_pjt/A4`로 이동 배치 완료.

### 18:50 ~ 20:19: `yongsoo` 통합, 안전 잠금 제거, `draw_image_standalone` 직결, `RECOVERY_REQUIRED` 제거 및 FastDDS `futex_do_wait` 버그 해결

- **2026-11-17 18:50:02 ~ 19:26:41** (`5c4f39b9` #1~#17 + 브라우저 서브에이전트 `db78db5e`) **`yongsoo` 274항목 통합 및 초기 실기 연동 디버깅**
  - `18:50:02 ~ 18:51:37`: `yongsoo.tar.gz`(274개 항목) `/home/qownsdud/ws_cobot_pjt/A4`에 압축 해제, `ws_dsr/install/setup.bash` 소싱으로 7개 ROS 2 패키지 최초 빌드 성공.
  - `18:56:24 ~ 19:01:23`: Notion 재확인(브라우저 Takeover 중단) 및 로컬 문서 기준 현황 보고.
  - `19:04:01 ~ 19:08:57`: 사용자 지시("`collaborate1`에 동작 다 있으니 안전 잠금 제거·불필요 파일 `back/` 이동")에 따라 `back/` 생성, `equipment_settings.py`·`drawing_node.py`·`doosan_adapter.py`·`gripper_controller.py`의 `hardware_validated`/해시/DI 잠금 전면 제거 및 `~/.ros/*.json` 자동 로드 구현(임의 자동 `submitDraw()`도 추가).
  - `19:10:52 ~ 19:11:55`: `ModuleNotFoundError: No module named 'uvicorn'` 해결(`fastapi`, `uvicorn`, `httpx`, `python-multipart` 시스템 설치, 38개 테스트 통과).
  - `19:13:52 ~ 19:15:38`: 사용자 항의로 임의 자동 `submitDraw()` 즉시 철회; 직전 자동 작업(`0b4ab5f7`)의 `RECOVERY_REQUIRED` 잠금(`.current_workflow.json`, `~/A4/data/jobs_real_v1.db*`) 삭제로 해제.
  - `19:21:31 ~ 19:25:40`: `슬롯 접근 높이보다 안전 이동 높이가 낮습니다` 오류 → `travel_z_mm`을 `268.62 → 476.73 mm`로 수정; 실물 기동 직후 극심한 저속 문제 → 같은 펜 연속 획 `stroke_lift_mm=4 mm` 유지, `use_spline=True`, `travel=150`/`draw=60`/`pick=80`/`acc=150` 상향.
- **2026-11-17 19:27:14 ~ 19:44:26** (`ba08c363` #1~#7) **`draw_image_standalone` 이식, `SetCurrentTool` 수정 및 `RECOVERY_REQUIRED` 완전 제거**
  - `19:28:13 ~ 19:35:54`: `art_drawing_controller`에 `draw_image_standalone` 로직·파라미터(`calibration_probe.py`, `STICK_GRIP_RZ_OFFSET_DEG=-45.0°`, `GripperController.off()`, `test_standalone_parity.py`) 이식.
  - `19:36:38 ~ 19:40:15`: `~/A4/data/jobs_real_v1.db` 첫 작업(`8b69e9d5`) 실패 원인 규명 — `SetCurrentTool("Tool_Weight")` `success=False` 시 `DRIVER_REJECTED_SET_TOOL` 예외로 중단되던 문제를 원본 `DSR_ROBOT2.py`처럼 경고 로그 후 계속 진행으로 수정.
  - `19:41:21 ~ 19:44:26`: 카메라 버튼 잠금 원인(`jobs_real_v1.db`에 남은 `RECOVERY_REQUIRED` / `UNCONFIRMED_AFTER_RESTART`, 복구 필요 상태) 확인 → `production_engine.py`·`job_repository.py`에서 `RECOVERY_REQUIRED` 잠금 제거 및 재시작 시 `STOPPED` 자동 정리 적용(`jobs_real_v1.db`에 `35f6aa51`, `55746df4` `HOLD_POSE_CHANGED` 기록됨).
- **2026-11-17 19:47:57 ~ 20:19:51** (`9c45e5f0` #1~#15) **`control/` 분리, `standalone_drawer` 4노드 직결, `state.blocked` 제거 및 FastDDS `futex_do_wait` 버그 규명·수정**
  - `19:47:57 ~ 19:53:07`: `yongsoo` 파일 중 키오스크·선화·경로추출만 남기고 `art_job_manager`·`art_drawing_controller`·관련 문서/테스트를 `control/` 폴더로 분리(`86 passed, 1 skipped`).
  - `19:55:05`: 신규 노드 `art_artwork_pipeline/standalone_drawer.py` 작성 — 키오스크 **그리기** 클릭 시 `drawing_plan.json` → `standalone_strokes.json` 변환 후 `ws_dsr`의 `draw_image_standalone.py`를 직접 실행하고 `CANCEL` 시 `'x\n'` 전달. `art_system.launch.py`를 4노드(`artwork_pipeline`, `standalone_drawer`, `bridge`, `kiosk`)로 구성.
  - `20:01:05`: `Ctrl+Z`로 중지된 잔여 프로세스(`8000`/`8001` `address already in use`) `pkill -9` 정리.
  - `20:04:43 ~ 20:05:48`: 작업 `fd7b2195`(`Doosan Rokey AAAA`) 잔여 `.current_workflow.json`으로 카메라 비활성화 → `app.js`의 `state.blocked` 분기 전면 제거 및 `workflow.py` 완화.
  - `20:09:51 ~ 20:11:28`: `ModuleNotFoundError: No module named 'mediapipe'`(`~/A4/data/jobs/43e4a185` 실패 흔적) → `ART_LINEART_METHOD=cv` 및 `scripts/setup_lineart_env.bash`(`~/.venvs/a4-lineart`) 설치 양쪽 완료.
  - `20:12:53 ~ 20:18:51`: 작업 `289a44a5`(78획), `df55908c`에서 로봇 무동작 원인 규명 — **`draw_image_standalone.py` 기동 0.07초 만에 `set_tool()` 호출 시 `DSR_ROBOT2` 내부가 `wait_for_service()` 없이 즉시 `call_async()` + `spin_until_future_complete()`를 호출해 FastDDS 디스커버리 전 요청이 유실되어 `futex_do_wait` 무한 대기에 빠지는 버그** 발견! `draw_image_standalone.py` L810-820에 `_ros2_move_joint`·`_ros2_set_current_tool` `wait_for_service(timeout_sec=15.0)` 추가(`20:18:51`), 직후 `20:19:51` 작업 `b8a42bb3` 및 `ws_dsr/drawing_previews/latest_preview.png` 검증 완료.

---

## 6장. 완전 독립 배포화, `JobManager`·`SQLite` 통합, TCP `-230mm` 보정, RGB 다양화, 실기 9연전 및 한글 캘리그라피 (2026-11-18)

*(당일 `A4`에서 **42회** `colcon build`(전원 성공), **130개** 작업 생성, 대화 6건(`ba08c363`, `5c4f39b9`, `3040210a`, `9c45e5f0`, `bb64c38c`, `df415475`)과 팀원 3명(`TW-94-git`, `RyuM-S`, `dduter`) 커밋이 하나로 대통합된 핵심 개발일.)*

### 09:27 ~ 13:02: 아키텍처 정리, `A4` 완전 독립(`vendor/`·`config/`), SQLite 분리 `art_job_manager` 신규 구현 및 신호 규격 확정

- **2026-11-18 09:27:33 ~ 09:31:33** (`ba08c363` #8~#10) 첨부 아키텍처·플로우차트(`5a3ecfd` 5노드)와 현재 4노드(`kiosk`, `bridge`, `artwork_pipeline`, `standalone_drawer`) 직결 구조 비교 및 `JobManager` 상태(`QUEUED`~`RECOVERY_REQUIRED`)·`SQLite` 용어 정리.
- **2026-11-18 09:34:14 ~ 09:35:11** (`5c4f39b9` #18) + `[Git]` **`A4` 워크스페이스 Git 공식 초기화 (`f00e4d6`)**
  - `/home/qownsdud/ws_cobot_pjt/A4`에 `git init` 및 `origin` 연결 후 기존 `bae`(`82ca6eb`)를 현재 `A4` 구조로 교체하는 커밋 **`f00e4d6`** (`09:35:05`, `Replace bae branch with current A4 workspace`, 1,880개 파일, +444,568 / -300,895줄) 푸시.
- **2026-11-18 10:24:33 ~ 11:13:18** (`ba08c363` #11~#21) **순수 인메모리 `JobManager` + 단방향 `SQLite` 분리 아키텍처 설계 구상**
  - 기존 강결합 구조(`jobs_real_v1.db` 트랜잭션 기반 상태 머신 → 재시작 잠금 `RECOVERY_REQUIRED` 유발)에서 벗어나, **`JobManager`는 인메모리 중앙 판단만 수행하고 결정 이벤트(`JobDecision`)를 단방향으로 발행하며, 별도 `SQLite` 모듈이 이를 구독해 저장하는 분리 설계** 확정.
- **2026-11-18 11:18:18 ~ 11:28:26** (`ba08c363` #22~#26, `5c4f39b9` #19~#21) + `[Git]` `back/` 일괄 격리, `draw_image_standalone.py` 내재화 및 `bae` 정리
  - 미사용 문서 6종·`checkpoint_stub.py`·`local_test_env.bash`를 `back/control/`로 이동 및 `back/README.md` 신설.
  - 외부 `ws_dsr` 의존 제거 1단계: `draw_image_standalone.py`(959줄)를 `art_artwork_pipeline/`으로 복사 내재화하고, `pipeline_runner.py`에 `a4_root()` 헬퍼를 추가해 `~/A4/data/jobs` 대신 현재 `A4/data/jobs` 기준으로 통일.
  - 커밋 **`ded34bf`** (`11:26:04`, `Sync workspace updates to bae branch`, 15개 파일) → 이어서 Git 추적에서만 `back/` 제외(`.gitignore` 추가, 로컬 `back/` 유지)한 커밋 **`6c31b00`** (`11:28:24`, `Remove back directory from bae branch`, 192개 파일, -441,184줄) 푸시.
- **2026-11-18 11:34:25 ~ 11:47:40** (`ba08c363` #27~#34) **`vendor/` 두산·그리퍼 드라이버 편입 및 `~/.ros/*.json` 이동 — `A4` 완전 독립 빌드 달성!**
  - `ros2_ws/src/vendor/`에 `doosan-robot2`(6개 패키지: `dsr_msgs2`, `dsr_common2`, `dsr_controller2`, `dsr_hardware2`, `dsr_description2`, `dsr_bringup2`)와 `rg2`(`m0609_rg2_bringup`), `onrobot-ros2`(`onrobot_rg_description`, `onrobot_rg_msgs`) 복사 편입.
  - `ws_dsr` 미소싱 상태에서 **14개 패키지 단독 전체 `colcon build` 성공**(`11:40:00 ~ 11:42:39`, 3분 59초).
  - `~/.ros/{plane_calibration, pen_slots, stick_slot, draw_height_test_state}.json` 4개 파일을 `A4/config/`로 완전 이동(`mv`)하고 코드 내 `.ros/` 폴백 참조 0건 확인. 전체 용량 `1.2 GB`(소스 배포 시 약 `360 MB`).
- **2026-11-18 11:39:36** `[Git]` 팀원 `TW-94-git` (`origin/jang`, 부모 `6c31b00`) 커밋 **`c1cba16`** (`Sync bae branch and update face ROI lineart & balanced path planner (len>=8.0, eps=1.5)`, 5개 파일, +158줄)
  - 내용: `lineart_cv.py`에 OpenCV Haar Cascade 정면 얼굴 타원 ROI 마스크(`cy=y+0.35h, rx=0.54w, ry=0.80h`, `face_canny 28~75`, `face_line_thickness=2`) 추가, `extractor.py`/`cli.py`/`visualize.py` Balanced 기본값(`epsilon=1.5`, `min_length_px=8.0`, `smooth_iterations=0`) 및 `render_balanced_preview()` 추가.
- **2026-11-18 11:48:41 ~ 12:24:15** (`ba08c363` #35~#43) **신규 SQLite 분리 `art_job_manager` 패키지 구현 및 검증**
  - `ros2_ws/src/art_job_manager/` 신규 구현: `plan_validator.py`(경로 보안·v0.1/v0.2·SHA-256 검증), `decision_port.py`(`JobDecision`, `DecisionSink`), `state_machine.py`(인메모리 단일 작업, `request_id` 멱등성, `RECOVERY_REQUIRED` 잠금 제거), `job_manager_node.py`.
  - 단위 테스트 5건 + `FakeControllerNode` ROS 2 통합 테스트(`test_job_manager_ros.py`) **6 passed in 0.76s** 통과.
- **2026-11-18 12:23:34 ~ 12:26:38** `[Git]` + (`3040210a` #7) 팀원 `RyuM-S` (`origin/ryu`) 커밋 **`9d3a896`** (`Move calligraphy scripts and previews to src/calligraphy`, 6개 파일: `calligraphy_path_gen.py`, `draw_calligraphy.py`, `README.md`, `preview_안녕_*.png` 2장) → 3분 만에 사용자가 `sparse clone`으로 `~/Downloads/calligraphy`에 내려받아 확보.
- **2026-11-18 12:35:24 ~ 12:38:38** (`5c4f39b9` #22~#24) + `[Git]` 커밋 **`f01683c`** (`12:36:25`, `bae`, `Update bae branch with self-contained config, vendor, art_job_manager, and standalone drawer`, 873개 파일, +197,395줄) 푸시(`doosan-robot2` 제외안 → 29초 만에 포함 결정). 순정 PC 배포 시 필요 조건(`rosdep`, Python 웹/비전 패키지, `colcon build`) 점검.
- **2026-11-18 12:41:31 ~ 13:02:40** (`ba08c363` #44~#50, `9c45e5f0` #16) **`art_drawing_controller` 복원·5노드 전환 및 `SQLITE_SIGNAL_CONTRACT_KR.md` 확정**
  - `back/control`에서 `art_drawing_controller` 복원, `ControlDrawing` 요청 시 `execution_id` 누락 버그 발견·수정, `art_system.launch.py` 5노드(`artwork_pipeline`, `job_manager`, `drawing_controller`, `bridge`, `kiosk`) 교체(`12:51:33`).
  - **12:48:39** `[Git]` 팀원 `TW-94-git` (`origin/jang` HEAD) 커밋 **`e7524ac`** (`Add slider-based CV density interpolation and detail_level persistence in pipeline_runner`): 0~100 슬라이더 → 유효 구간 `20.0~80.0` 매핑 + 5단계 `DENSITY_ANCHORS`(`Minimal`~`Very Rich`) 선형 보간 및 `detail_level` 저장 구현.
  - **12:55:12 ~ 13:00:12**: 4개 영역 신호 리스트 검토 후 `/art/job_decision`(`art_interfaces/msg/JobDecision`, QoS `RELIABLE`/`VOLATILE`/`KEEP_LAST(100)`, 15필드, 기본 이벤트 8종 + 예외·외력·복구 5종) 확정 및 **`docs/SQLITE_SIGNAL_CONTRACT_KR.md`** 작성.
  - **13:02:40**: 팀원 전달용 `job_manager_node.py` ↔ `art_state_store` 연동 설계안 사전 검토(1단계 `SqliteDecisionSink` 4개 보완점, 2단계 `ExecuteDrawing.action` 계약 필드 부재 지적).

### 13:58 ~ 15:38: `RyuM-S` `art_state_store` 정식 패키지화, TCP `Z=230mm` 보정 및 A4 통합 첫·두 번째 실기 완주

- **2026-11-18 13:58:17 ~ 14:16:17** (`9c45e5f0` #17~#26) + `[Git]` **`art_state_store` 편입으로 17패키지 풀 워크스페이스 완성**
  - `13:58:17`: 계약 유지 선에서 `job_manager_node.py`에 SQLite 1단계 연결(`_load_sqlite_classes`, `ART_STATE_DB_PATH`, `recover_after_restart()`, `destroy_node` `close()`) 구현.
  - `14:04:10` `[Git]`: 팀원 `RyuM-S` (`origin/ryu` HEAD) 커밋 **`43418d8`** (`Add standalone art_state_store module for SQLite state & recovery waypoints`, 8개 파일, +1,139줄 — 6테이블 `schema.sql`, WAL `RobotStateStore`, `SqliteDecisionSink`, `MotionRingBuffer`, `ExternalForceGuard`, `RecoveryWaypoint`, `COLCON_IGNORE`).
  - `14:05:27 ~ 14:07:13`: `origin/ryu`에서 `art_state_store` 체크아웃 → `COLCON_IGNORE`와 미사용 `sqlite_store_node.py` 제거 → 표준 `ament_python` 패키지화(`package.xml`, `setup.py`, `schema.sql` `package_data`, `art_job_manager` `exec_depend`) → **17패키지 풀 워크스페이스**(`art_*` 8개 + `vendor` 9개) 완성(`simulate_flow`·`pytest 7 passed`).
  - `14:13:15 ~ 14:16:17`: `Package 'art_bringup' not found`(새 터미널 source 안내) 및 `sqlite3` CLI 미설치 → Python 내장 `sqlite3` 조회 확인.
- **2026-11-18 14:17:49 ~ 14:27:00** (`9c45e5f0` #27~#33) **`art_state.db` 실전 첫 기록 및 `standalone_executor` 통합**
  - `14:17:49` (`a0c1234f`): `sodreal` 미기동 상태에서 그리기 클릭 → `DRIVER_UNAVAILABLE_OR_TIMEOUT`으로 안전 `STOPPED`(중단 종료) + `art_state.db` `jobs`/`job_events` 최초 정상 기록 검증.
  - `14:19:08` (`45bfe286`): 실물 연결 후 그리퍼만 닫고 멈춤 → `art_drawing_controller` `preflight()` `stationary()` 허용치 `0.1 mm / 0.1°`가 실물 미세 노이즈에 `HOLD_POSE_CHANGED`(정지 자세 이탈) 예외를 유발함을 진단.
  - `14:21:50`: `JobManager`(+SQLite)와 `draw_image_standalone.py`를 연결하는 **`art_drawing_controller/standalone_executor.py`**(`standalone_controller` 노드, `/art/execute_drawing` Action 구현) 신설 및 `art_system.launch.py` 듀얼 모드(`controller_mode:=standalone` 기본, `ros` 선택) 구성(`8 passed`).
  - `14:25:05 ~ 14:27:00` (`b5b89b7f`): `STANDALONE_DRAW_FAILED`(`~/.ros/stick_slot.json` 미존재) → `standalone_executor.py`의 외부 `ws_dsr`/`.ros/` 참조를 전면 제거해 `A4` 내부 경로만 사용하도록 통일.
- **2026-11-18 14:28:42 ~ 14:38:50** (`9c45e5f0` #34~#40) **TCP `GripperDA_v1` `Z=230 mm` 불일치 규명 및 `-230.0 mm` 일괄 보정!**
  - `14:28:42` (`d4bca46f`), `14:35:08` (`46b3acb6`): 캘리브레이션과 펜 집기가 20~30 cm 공중에서 동작하는 이상 현상 발생.
  - 원인 규명 (`14:36:57`): 11/16 최초 9점 캘리브레이션·슬롯 티칭 당시에는 플랜지(`TCP Z=0`) 기준(`바닥 Z≈237.9 mm`, `슬롯 Z≈366.7 mm`)으로 저장되었으나, 이후 티치 펜던트 `GripperDA_v1`에 실제 그리퍼 길이 **`TCP Z = 230 mm`**가 설정되면서 전 좌표가 정확히 `+230 mm` 상승함.
  - 보정 (`14:38:03 ~ 14:38:19`): `A4/config/` 3개 JSON 일괄 `-230.0 mm` 보정 적용:
    - `plane_calibration.json`: `c` `237.340 → 7.340 mm`, 9점 `z` `7.637 ~ 8.622 mm`
    - `stick_slot.json`: `z` `366.725 → 136.725 mm`
    - `pen_slots.json`: `PEN_1~3` `z` `366.72~366.73 → 136.72~136.73 mm`
- **2026-11-18 14:39:31 ~ 14:49:52** `[DB/실기]` **A4 통합 시스템 최초 실기 완주 성공!**
  - 작업 ID `60dbe6cf`(`cv`, `"AAAA"`, 66획): **`COMPLETED` (소요 621.7초 = 10분 22초)**. 진행 중 `14:41:35 ~ 14:42:28` (`9c45e5f0` #41~#43) `art_state.db` 실시간 조회·시각화 방법(`watch`, `SQLite Viewer`) 확인.
- **2026-11-18 14:46:55 ~ 14:57:55** (`ba08c363` #51~#56) `origin/jang`(`c1cba16`, `e7524ac`) 선화 고도화 로직 로컬 이식
  - `lineart_cv.py`(Haar 얼굴 ROI + 차등 Canny `28~75`, `face_line_thickness=2`), `extractor.py`/`cli.py`/`visualize.py`(Balanced 기본값), `pipeline_runner.py`(`DETAIL_LEVELS = {'low': 0.0, 'medium': 50.0, 'high': 100.0}` 및 0~100 → `20~80` 5단계 `DENSITY_ANCHORS` 선형 보간, `simplify_tolerance_mm=0.0`) 반영 완료.
- **2026-11-18 15:18:35 ~ 15:38:11** `[DB/실기]` **2번째 실기 완주 (`c135a9f2`, `cv`, `detail=100.0`, `"AAAA"`, 105획, 1,175.3초 = 19분 35초)** — 직후 RGB 색 다양화 벤치마크 기준 사진으로 활용됨.

### 15:31 ~ 16:41: RGB 3색 균일·랜덤 배정, 55mm 획 분할, 개츠비 GrabCut 인물 분리·완주 및 대통합 커밋 `a4c3a90`

- **2026-11-18 15:31:06 ~ 15:56:25** (`bb64c38c` #1~#13) **RGB 3색 획 단위 균일·랜덤 배정 및 긴 획 분할 알고리즘 구현**
  - `15:31:06 ~ 15:35:20`: 기존 4×4 격자(`balanced_cells`, 6/5/5) 뭉침 진단 → **긴 획 내림차순 + 최근접 이웃(`neighbor_k=3`) 색 회피 + 누적 길이 균형(`pen_totals`)** 알고리즘 설계.
  - `15:37:56 ~ 15:40:27`: `puzzle/colors.py`에 `assign_stroke_pens()` 구현 및 `drawing_plan.py` v0.2 `grid_id` 호환 매핑(`15 passed`).
  - `15:41:03 ~ 15:43:46`: `svg_exporter.py` `PEN_COLORS`를 기존 검/빨/파에서 **RGB(`PEN_1` Red `#e53935`, `PEN_2` Green `#2e7d32`, `PEN_3` Blue `#1565c0`)**로 수정. `c135a9f2`(97획) 검증: Red 33획 `483.5 mm` / Green 32획 `484.7 mm` / Blue 32획 `483.6 mm` (완벽한 1:1:1).
  - `15:47:52 ~ 15:53:06`: 긴 선 단일 색 방지용 **`split_long_stroke(points, max_length_mm=55.0)`**(임계 `60.5 mm`, 최소 분할 `30.3 mm ≥ 25 mm`) 구현 및 `pipeline_runner.py` 연결(`16 passed`).
  - `15:54:21 ~ 15:56:25`: 분할 조각 2개가 우연히 동색을 받아 `optimize_plan()`의 `linemerge`로 다시 `89.7 mm`/`79.3 mm`로 합쳐지던 버그 발견 → `drawing_plan.py`가 연속 분할 쌍 `connected_pairs`를 전달하고 `colors.py` 최우선 키로 **연속 분할 조각 간 이색 강제** 적용 → 최대 단일 선 길이 **`89.7 mm → 49.3 mm`** 감소 확인 후 빌드 완료.
- **2026-11-18 15:58:33 ~ 16:08:30** (`bb64c38c` #14~#17) **`Im_Gatsby.png` 얼굴 뭉개짐 해결 — GrabCut 인물 분리 + 배경 큰 윤곽선 균형 보존**
  - `15:58:33 ~ 16:00:23`: `Im_Gatsby.png` 6회 연속 테스트(`4c8bd44f`, 250획)에서 얼굴 뭉개짐 발생 → `16:01:15` / `16:03:01` 사용자 피드백("배경은 덜 따고 사람은 열심히 따라").
  - 개선 (`16:04:48`):
    1. `lineart_cv.py`에 **`_build_person_mask` (`cv2.grabCut` 3회 반복)** 인물 전경 분리 도입.
    2. 얼굴 뭉개짐 원인 제거: `face_line_thickness` `2 → 1`, 2단계 bilateral 필터(`d=7, sigma=55.0`), 얼굴 Canny `28/75 → 45/115` 상향, `DENSITY_ANCHORS` 전반 상향.
    3. `pipeline_runner.py` 벡터 정밀도 `epsilon` `1.5 → 0.9`, `bridge_gap_px` `4.5 → 4.0` (개츠비 98획).
  - `16:06:29 ~ 16:07:10`: "배경을 너무 없앴다" 피드백 → 배경 영역에 `GaussianBlur(7,7)` + `bilateral(9,85)` + 상향 Canny(`1.9×`/`1.6×`) + `connectedComponentsWithStats`(`area >= 28` 또는 `max(bw,bh) >= 26`) 적용해 보케 잡음만 억제하고 불꽃놀이 등 큰 배경 윤곽 보존(개츠비 154획, `16:06:51` 빌드).
- **2026-11-18 16:07:33** `[Git]` 팀원 `dduter` (`origin/yongsoo` HEAD, orphan 157개 파일, +16,206줄) 커밋 **`bc2f32c`** (`UI, 예외처리 수정`, 141 pytest passed) — 통합 UI(`/admin` 307 리다이렉트, `0~100` 슬라이더, PAUSE/RESUME/STOP 버튼, 외력 배너), `FORCE_STOPPED`/`RESETTING`, `live_control.py`(613줄), `recovery_store.py` 포함.
- **2026-11-18 16:14:18 ~ 16:46:48** `[DB/실기]` **3번째 실기 완주 — 개츠비(`Im_Gatsby.png`) RGB 균일 배정 첫 실물 완주!**
  - 작업 ID `74add98f`(`cv`, `detail=50.0`, `"Im Gatsby"`, 171획: `PEN_1:63 / PEN_2:55 / PEN_3:53`): **`COMPLETED` (소요 1,950.1초 = 32분 30초)**.
- **2026-11-18 16:40:36 ~ 16:41:03** (`5c4f39b9` #25) + `[Git]` **대통합 커밋 `a4c3a90`** (`bae`, 56개 파일, +4,103 / -60줄) — `TW-94-git` 얼굴 ROI/보간 + `bb64c38c` RGB/GrabCut + `RyuM-S` `art_state_store` 정식 패키지 + `art_drawing_controller` + TCP `-230 mm` 보정 + `Im_Gatsby.png` 일괄 반영.

### 16:42 ~ 18:43: `origin/yongsoo` 슬라이더·외력 예외처리 이식, `ros` 컨트롤러 실기 9연전 집중 디버깅 및 첫 전획 완주

- **2026-11-18 16:42:10 ~ 16:51:19** (`ba08c363` #57~#60) `origin/yongsoo`(`bc2f32c`) 비교 분석 및 로컬 구조 유지 최소 수정 이식
  - `art_kiosk`: `0~100` 슬라이더(`간략하게`/`표준`/`세밀하게`), `PAUSE`/`RESUME`/`CANCEL` 버튼, `FORCE_STOPPED`(외력 정지) 배너, `/api/kiosk/current/control` 추가.
  - `art_drawing_controller`: `DriverAlarmLatch`(`/{robot_id}/error` `RobotError` 구독), 6축 `read_tool_force()`, `art_state_store`의 `MotionRingBuffer`·`ExternalForceGuard`(초기 `15.0 N`) 연동 → 외력 감지 시 자동 홈 이동 금지·`recovery_checkpoints` 1건 저장·`FORCE_STOPPED` 보고.
  - `art_job_manager`: `FORCE_STOPPED` 상태 전이 반영(`9 passed`).
- **2026-11-18 16:54:53 ~ 17:04:12** (`ba08c363` #61~#65) 전수 호환성 점검 및 치명적 불일치 해결
  - 발견·수정: `art_kiosk_bridge/schemas.py` L66 `PrepareArtworkBody.detail`이 `Literal['high','medium','low']`로 고정돼 슬라이더 `0~100` 입력 시 HTTP 422가 나던 문제 수정; `art_system.launch.py` 기본 **`controller_mode:=ros`** 전환; 중복 `standalone_drawer.py` `back/control/` 이동(`16 passed`).
- **2026-11-18 17:09:12 ~ 18:31:51** (`ba08c363` #66~#92) **`ros` 실물 컨트롤러 집중 디버깅 9연전 (`Chiikawa` 8회 + `V`/`Um G` 실기 검증)**
  1. **실기 이상 #1 (`17:11:31 ~ 17:15:12`, `2b63c3c6`) `HOLD_POSE_CHANGED`(정지 자세 이탈)**: 공중에서 그리퍼만 닫고 정지 → `doosan_motion_control.py`·`doosan_adapter.py` 서보 정지/도달 허용치를 `0.1 mm/0.1°` → `0.5 mm/0.5°` → 현실적인 **`2.0 mm / 2.0°`, 속도 `1.0 mm/s`**로 완화; `at_pose()` 예외 대신 `False` 반환; `/admin` 정지 사유 배너 임시 추가.
  2. **실기 피드백 #2 (`17:19:03 ~ 17:20:22`) 모션 중간 지연 1차 최적화 & 9점 캘리브레이션 OFF**: `at_pose()` 3회 루프 제거, `motion_complete()` `check_motion` 우선 확인, 폴링 `0.02 → 0.05 s`, `equipment_settings.py` `auto_calibrate_9pt=False` 설정.
  3. **UI 단순화 (`17:21:03 ~ 17:21:56`)**: `/admin` 페이지 제거(`server.py` 라우트 삭제, `admin.html`/`admin.js` `back/control/` 이동) 및 메인 화면 `jobErrorLog` 구체적 사유 표시.
  4. **실기 이상 #3 (`17:18:05 ~ 17:22:25`, `665e5402` CP#1 `Fz=+14.73 N`) 공중 외력 오탐**: `external_force_limit_n`을 `15.0 → 20.0 N`으로 상향.
  5. **실기 피드백 #4 (`17:26:50 ~ 17:28:38`) 2~3초 대기 병목(DRFL 응답 큐 적체) 해결**: 이동당 수십 회 발생하던 `observed()`/`at_pose()` RPC를 제거해 **ROS 2 서비스 호출 95% 축소**(외력 확인 `0.1 s`, 루프 `0.03 s`).
  6. **실기 오류 #5 (`17:25:16 ~ 17:33:07`, `7565039c`) `완료 획의 실제 펜 이격 미확인`**: `pen_up_confirmed` 검증을 `ExecuteDrawing.action`, `JobStatus.msg`, `art_drawing_controller`, `art_job_manager`, `tests`, `docs` 전 패키지에서 완전 제거.
  7. **실기 UI 이슈 #6 (`17:38:09 ~ 17:52:33`, `952936a2` 64/134획) 제어 버튼 간헐 활성 + 라인 길이 `%` 진행률 + 캐시 무효화**: `job_manager_node.py`에 **`1.0 s` 주기 하트비트 `_status_timer`** 추가, `ART_STATUS_MAX_AGE_SEC` `5 → 15 s`, `workflow.py` `_plan_length_progress()`로 획 수 대신 **라인 길이 `%` 진행률(`50.0% (11/134획)`)** 도입, 브라우저 캐시 해결용 `?v=20261118` 쿼리 추가.
  8. **실기 오류 #7~#8 (`17:53:43 ~ 18:15:24`, `ba206797`, `eefb2e52`, `3eb797d8`) 일시정지/재개/정지 원상복구 완성**: `doosan_motion_control.py` 타임아웃 `3.0 → 8.0 s` 및 재시도 강화, `return_pen_and_home()`(기준 막대 `held_stick_pose`와 `held_pen` 모두 반납 후 홈 복귀), `PAUSE` 시 급정지(`move_pause`) 대신 **진행 중 모션 완료 후 홈 복귀 일시정지**(미파지 시 제자리 정지), `STOP_UNCONFIRMED`(이미 정지 `status==0` 시 `move_stop` 생략) 수정. 직후 `972e9151`에서 **PAUSE/RESUME 7회 연속 스트레스 테스트(명령 15건)** 성공!
  9. **실기 이슈 #9 (`18:21:47 ~ 18:26:22`, `79382622` CP#2·CP#3, `7d869849` CP#4) `FORCE_STOPPED` 후 즉시 반납 + 속도 대폭 상향**: 외력 감지 후 `RESUME` 성공 및 `FORCE_STOPPED` 상태에서 `CANCEL` 시 `/art/control_drawing` `RECOVER` 명령으로 즉시 도구 반납·홈 복귀 구현(`18:25:20`); `18:29:44 ~ 18:31:51` 드로잉 속도 상향(`draw 25/25 → 55/80`, `travel 80/80 → 130/130`, `pick 25/25 → 40/60`, `joint 60/60 → 75/75`, `acc 80 → 100`, `corner_angle_deg 35 → 50°`, 폴링 `0.03 → 0.015 s`).
  - *(도중 `18:01:53` #84에서 `PEN_1~3` `z_offset_mm`을 `13.5 → 13.8 mm`로 일시 상향 테스트함.)*
- **2026-11-18 18:34:41 ~ 18:43:37** `[DB/실기]` **4번째 실기 완주 — `ros` 컨트롤러 최초 64/64 전획 완주!**
  - 작업 ID `7d9e0245`(`cv`, `"A Moo Geo Na"`, `PEN_1:28 / PEN_2:18 / PEN_3:18`): **`COMPLETED` (소요 535.4초 = 8분 55초)**.

### 18:47 ~ 20:01: 한글·영문·특수문자 유니코드 캘리그라피 전면 개편, `NanumBrush.ttf` 설치, Z `12.5 mm` 하향 및 다른 노트북 RViz 대응

- **2026-11-18 18:47:01 ~ 18:48:34** (`9c45e5f0` #44~#46) `~/Downloads/calligraphy` 분석 및 **한글·영문·특수문자 캘리그라피 전면 개편**
  - `art_artwork_pipeline/calligraphy/generator.py` 전면 재작성: `skimage` 없이 `PIL` + `fontTools` + 순수 NumPy Zhang-Suen 세선화 + `cv2.approxPolyDP`, 문자별 다중 폰트 자동 폴백(`NanumBrush` → `NotoSerifCJK` → `NanumMyeongjoBold` → `NanumGothicBold` → `DejaVuSans-Bold` → `NotoSansSymbols`), 1 px 점(`. , ! ? i j`) 보존.
  - `art_kiosk` `app.js`/`index.html`에서 `^[A-Za-z ]*$` 영문 전용 제한 해제 및 `tests/artwork_pipeline/test_calligraphy_unicode.py` 신설.
- **2026-11-18 18:57:32 ~ 19:05:25** `[작업로그]` 유니코드 캘리그라피 최초 도입 시험(Session 06) — 긴 특수문자·자모 문구 테스트 중 초기 오류로 `LINEART` 단계 중단 25건 발생, `19:05:36` 이후 `PREPARED` 성공했으나 세선화 잔선으로 총 `976~1,021획` 폭증(`a23287ba`, `e6394e0a`).
- **2026-11-18 19:00:35 ~ 19:01:53** (`9c45e5f0` #47~#48) 글씨 왼쪽 정렬 + 그림 좌우 안쪽 `30 mm` 영역 제한(`paper.py` 가로 `50.0~247.0 mm` / 세로 `45.0~165.0 mm`), `maxlength` `24 → 60`.
- **2026-11-18 19:07:57 ~ 19:09:05** (`9c45e5f0` #49~#50) `a23287ba` 실행 중 살짝 공중에 떠 그리는 현상 진단 → 전체 펜 `z_offset_mm` 하향(`equipment_settings.py` `13.8 → 12.5 mm`, `draw_image_standalone.py` `[13.5, 13.5, 13.5] → [12.5, 12.5, 12.5]`). 직후 `19:10:17` `e6394e0a` 실기 테스트(317/976획 진행 중 `stroke=318` 외력 CP#5 `Fx=-25.24 N` → 안전 반납).
- **2026-11-18 19:20:24 ~ 19:23:43** (`9c45e5f0` #51~#53) **글자 순차 작성·2배 확대·원/곡선 점 찍힘 제거 및 `NanumBrush.ttf` 설치**
  - 한 글자씩 렌더링·추적 후 좌→우 순서 연결, `height_mm` `8.0 → 16.0 mm`(2배), `maxlength` `60 → 20`, 픽셀 방문 추적 + 직교 이웃 우선 + `max_spur_len=6` + `15 px` 미만 잔선 제거 + 닫힌 원/곡선 1개 연속 폐곡선(`approxPolyDP eps=0.5`, `"OOOOO"` 5원 검증 통과).
  - `sudo` 권한 없이 `apt-get download fonts-nanum-extra` + `dpkg-deb -x`로 `/home/qownsdud/.local/share/fonts/NanumBrush.ttf` 직접 설치·`fc-cache` 갱신 및 1순위 기본 폰트 지정.
- **2026-11-18 20:01:42 ~ 20:01:49** (`df415475`) 다른 노트북에서 발생한 RViz `Fixed Frame: No tf data. Frame [base_link] does not exist` 오류 문의 → 4단계 점검 절차(`robot_state_publisher`/`/joint_states`, `Fixed Frame` `world`/`base`, `ROS_DOMAIN_ID`/`LOCALHOST_ONLY`/`ufw`, `use_sim_time`) 안내.

---

## 7장. 4펜 체제 완성, 데스크톱 앱 런처, 가변 필압·고속 스플라인, 다국어 정자체 및 원클릭 배포 환경 구축 (2026-11-19)

*(당일 `A4`에서 **35회** `colcon build`(전원 성공) + 1회 `colcon list`, **113개** 작업 생성, `PEN_4` 4펜 확장·원클릭 앱 구축·7대 최적화·실기 완주 5건(`0ca1f525`, `d415974e`, `cb1ed8e7`, `4d7c6b73`, `3b83abc6`)·`main` 동기화(`464c6ac`)·다국어 정자체·`경로 추출` 수동 버튼·`setup_env.bash` 원클릭 배포 환경 구축까지 수행.)*

### 09:30 ~ 12:21: `jang` 동기화, 검정 4번 펜(`PEN_4`) 도입, `test_stick_and_pens.py`, 슬롯·높이 미세 튜닝, `lineart_comparison.md` 및 데스크톱 앱 구축

- **2026-11-19 09:30:09** `[Git]` 팀원 `TW-94-git` (`origin/jang`) 커밋 **`34ae5d9`** (`Merge remote-tracking branch 'origin/bae' into jang`).
- **2026-11-19 09:58:50** (`9c45e5f0` #54) **마지막 글씨 전용 4번째 검정 펜 `PEN_4` 도입**
  - `svg_exporter.py` `PEN_COLORS`에 `'PEN_4': '#111111'` 추가, `calligraphy/generator.py`·`pipeline_runner.py` 글씨 기본 `pen_id='PEN_4'`(항상 마지막 실행), `drawing_plan.py`/`plan.py`/`plan_validator.py` `PEN_4` 허용, 컨트롤러·standalone 4슬롯(`[12.5, 12.5, 12.5, 12.5]`) 확장.
- **2026-11-19 10:02:54 ~ 10:03:07** (`ba08c363` #93, 대화 종료) 현재 파일 상태 인지 최신화 및 5노드 `ros` 컨트롤러 작업 수행 매뉴얼 정리.
- **2026-11-19 10:05:39 ~ 10:29:16** `[파일/작업로그]` **명화·샘플 3종 추가 및 68건 대량 프리뷰 튜닝 세션 (Session 07)**
  - `pictures/죽기 딱 좋은 날씨네.png`(`10:15:09`), `pictures/별이 빛나는 밤.jpg`(`10:24:43`), `pictures/뭉크의 절규.jpg`(`10:25:59`) 추가.
  - `PEN_4` 최초 적용 36건 포함 총 68건 프리뷰 생성(`I'm Gatsby!`, `Chiikawa`, `죽기 딱 좋은 날씨네~`, `10:29:16` `ea485b2d` `"뭉크의 절규, The Scream"`).
- **2026-11-19 10:31:39 ~ 10:38:52** (`9c45e5f0` #55~#56) `PEN_4` 직접교시 좌표 측정(`Tool_Weight`, `GripperDA_v1 Z=230 mm`, `[565.97, 78.25, 156.58, 10.81, -178.99, 10.78]`) → Z를 1~3번 펜과 동일한 `136.73 mm`로 통일해 `config/pen_slots.json` 등록.
- **2026-11-19 10:42:17 ~ 10:42:55** (`5c4f39b9` #26) + `[Git]` **커밋 `c503395`** (`origin/bae` HEAD 및 `origin/main` 동시 푸시, 47개 파일, +1,260 / -845줄) — 한글 캘리그라피·`PEN_4`·구 `standalone_drawer`/`admin.html`/`admin.js` 삭제·명화 3장 동기화.
- **2026-11-19 10:46:42 ~ 11:08:16** (`9c45e5f0` #57~#58) **독립 하드웨어 점검 스크립트 `scripts/test_stick_and_pens.py` 신설** — 기준 막대 바닥 탐색 + 선택한 펜(`1~4`) 픽업·`30 mm` 테스트 직선·반납 + `'x'` 키 안전 복귀(`--only-stick`, `--pens`, `--no-draw`, `--z-offset`, `--virtual`, `--dry-run`). (`11:08:16` 실행 경로 `../scripts/test_stick_and_pens.py` 안내.)
- **2026-11-19 10:57:28** `[Git]` 팀원 `TW-94-git` (`origin/jang`) 커밋 **`0b44d8d`** (`Merge branch 'main' into jang` — `c503395` 반영).
- **2026-11-19 11:18:30 ~ 11:23:50** (`9c45e5f0` #59~#61) **`config/pen_slots.json` X 좌표 실기 미세 보정**
  - `11:18:30`: `PEN_2` X `568.266785 → 567.466785 mm`(`-0.8 mm`), `PEN_3` X `568.258789 → 567.958789 mm`(`-0.3 mm`).
  - `11:19:09` → `11:23:39`: `PEN_4` X `565.97 → 566.47` (`+0.5 mm`) → **`567.47 mm`** (`+1.0 mm`, 최종값 확정).
- **2026-11-19 11:37:24 ~ 12:05:05** (`9c45e5f0` #62~#77) **`PEN_3`(파란 펜) Z 오프셋 11단계 초정밀 실기 튜닝**
  - `12.5` → `12.7` (`11:37:55`) → `13.0` (`11:41:38`, 펜촉 길이 확인) → `13.5` (`11:44:15`) → `14.0` (`11:46:17`) → (`11:48:54` `PEN_1=Red`, `PEN_2=Green`, `PEN_3=Blue`, `PEN_4=Black` 색상 매핑 확인) → `16.0` (`11:49:28`, `test_stick_and_pens.py`에도 펜별 배열 적용) → `14.5` (`11:51:59`) → `14.2` (`11:53:55`) → `13.9` (`11:55:57`) → `13.7` (`11:58:09`) → `13.5` (`12:00:00`) → **`13.2 mm`** (`12:01:59`, 중간 확정 `[12.5, 12.5, 13.2, 12.5]`).
  - `12:05:05`: `draw_image_standalone.py` `AUTO_CALIBRATE_9PT = False` 기본 OFF 재확인.
- **2026-11-19 12:07:27 ~ 12:12:52** (`9c45e5f0` #78~#84) **데스크톱 앱 설계 + `cv` vs `mfl_ld` 비교(`lineart_comparison.md`) 및 임시 전환 버튼**
  - `ea485b2d`(뭉크의 절규)로 두 엔진 직접 비교 → 아티팩트 `lineart_comparison.md` 생성(`cv`: ~68 ms 얇고 정갈 / `mfl_ld`: 4~5초, 명암·이목구비 풍부한 스케치).
  - `face_landmarker.task`를 `~/.cache/a4/models/face_landmarker.task`로 복사하고 키오스크 상단 바에 `#btnToggleMethod`(`cv` ↔ `mfl_ld`) 전환 버튼 임시 추가.
- **2026-11-19 12:14:15 ~ 12:21:24** (`9c45e5f0` #85~#90) **원클릭 데스크톱 응용프로그램 `A4 Drawing Studio` 구축 및 실행 오류 해결**
  - 생성 파일: `scripts/a4_app_icon.svg`(128×128 전용 아이콘), `scripts/launch_a4_app.bash`(`flock` 중복 방지, `zenity` 진행/오류 창, `sodreal` 기동·`/dsr01` 25초 대기 → `art_system` 기동·`/api/health` 20초 대기 → `google-chrome --app="http://127.0.0.1:8000" --start-maximized`, 창 닫힘 시 `trap cleanup`으로 양쪽 프로세스 그룹 `SIGINT`/`SIGTERM` 자동 종료), `scripts/stop_a4_app.bash`, `/home/qownsdud/Desktop/A4_Drawing.desktop`, `~/.local/share/applications/a4-drawing.desktop`.
  - 트러블슈팅 1 (`12:15:53`): `.desktop` 더블클릭 시 텍스트 편집기로 열림 → `DBUS_SESSION_BUS_ADDRESS` 지정해 `gio set ... metadata::trusted true` 재적용.
  - 트러블슈팅 2 (`12:19:12`): `gripper_joint_state_publisher.py not found` 오류 → `launch_a4_app.bash`가 `sodreal` 전에 `A4/ros2_ws/install/setup.bash`를 먼저 `source`해 `m0609_rg2_bringup` 경로가 충돌함 → `ws_dsr`만으로 `sodreal`을 먼저 기동한 뒤 `A4` 워크스페이스를 `source`하도록 순서 수정.
  - `12:21:24`: Chrome 업데이트 요청 → 현재 `154.0.8037.57` 확인 및 `sudo apt` 명령 안내.

### 12:33 ~ 15:08: `mfl_ld`+4펜 첫 완주, 가변 필압 캘리그라피·사람 필순, 7대 대규모 최적화, 곡률 스플라인 감속, 최종 완성작 완주 및 `main` 최종 동기화

- **2026-11-19 12:33:52 ~ 13:07:15** `[DB/실기]` **5번째 실기 완주 — `mfl_ld` + 4색 `PEN_4`(한글 붓글씨) 최초 완주!**
  - 작업 ID `0ca1f525`(`mfl_ld`, `"AAAA - 퍼즐 드로잉!"`, 329획: `PEN_1:99 / PEN_2:98 / PEN_3:99 / PEN_4:33`): **`COMPLETED` (소요 2,002.3초 = 33분 22초)**.
- **2026-11-19 12:48:28 ~ 13:07:16** (`9c45e5f0` #91~#96) **`PEN_1`/`PEN_3` 추가 하향 및 Z 높이 기반 가변 필압 캘리그라피(`0.0 ~ -1.0 mm`) 구현**
  - `12:48:28`: `PEN_1` `12.5 → 12.2 mm` 하향 및 현재 문자 필압(힘/순응 제어) 미적용(고정 Z 위치제어 + `20 N` `ExternalForceGuard`만 사용) 확인.
  - `13:01:21`: `PEN_1` `12.2 → 12.0 mm`, `PEN_3` `13.2 → 13.0 mm` 하향(`[12.0, 12.5, 13.0, 12.5]`).
  - `12:51:18 ~ 13:07:16`: `calligraphy/generator.py`에 `cv2.distanceTransform` 로컬 반지름 측정 + `8 px` 간격 세분화로 점별 **`z_deltas_mm` (`0.0 ~ -1.0 mm`)** 생성 구현, `standalone_executor.py`·`draw_image_standalone.py`·`paper_transform.py`·`stroke_executor.py` 전 경로 Z 반영 완료.
- **2026-11-19 13:13:02 ~ 13:55:40** `[DB/실기]` **6번째 실기 완주 — 가변 필압 붓글씨 + 417획 최장 기록 완주!**
  - 작업 ID `d415974e`(`mfl_ld`, `detail=100.0`, `"A4 - 퍼즐 드로잉!"`, 417획: `PEN_1:130 / PEN_2:131 / PEN_3:130 / PEN_4:26`, `z_delta=True`): **`COMPLETED` (소요 2,557.8초 = 42분 38초)**.
- **2026-11-19 13:55:31** (`9c45e5f0` #97) **사람 필순·방향 정규화(`_orient_human_stroke`) 구현**
  - `calligraphy/generator.py`: 시작점 `y`(위쪽) 우선 정렬, 세로·사선 획은 위→아래, 가로 획은 왼→오, 닫힌 획(`ㅇ`, `O`, `0`)은 최상단 시작 반시계 방향, 한 글자 내부 획 순서는 `x + 0.85 * y`(한글 초성→중성→종성) 정렬 적용.
- **2026-11-19 14:06:26** (`9c45e5f0` #98) **7대 대규모 품질·속도·UI 최적화 일괄 구현**
  1. **잉크 번짐 방지 1 — 점 체류 최소화**: `path_optimizer.py` `_clean_dwell_points`(`simplify_tolerance_mm` `0.0 → 0.22`, `min_point_spacing_mm=0.85`, `min_stroke_mm=2.5` → `0.8 mm` 미만 세그먼트 **89~96% 감소**), `split_at_corners` `min_arm_mm=1.2` & `corner_angle_deg → 55.0°`, `self._last_force_check` 인스턴스화로 불필요한 RPC 대기 제거, 폴링 `15 → 5 ms`, 종이 터치다운 전용 속도 `pen_down` `65.0 mm/s / 180.0 mm/s²` 분리.
  2. **잉크 번짐 방지 2 — 중복 덧칠 차단**: `path_optimizer.py` `_limit_ink_overdraw`(`max_passes=1`, `cell_mm=0.5`, `patch_mm=3.0`, `max_local_ink_mm=6.5`, `allow_cross_mm=1.8`).
  3. **그리기 속도 1.5배 상향**: `draw_velocity` `55.0 → 82.5 mm/s`, `travel_velocity` `130.0 → 150.0 mm/s`.
  4. **고속 대응 가속도 상향**: `draw_acceleration` `80.0 → 200.0 mm/s²`, `travel_acceleration` `130.0 → 220.0 mm/s²`, `pick_acceleration` `60.0 → 80.0 mm/s²`, 기본 `acceleration` `100.0 → 200.0 mm/s²`.
  5. **UI 물리 기반 그리기 예상 시간 및 `%` 바**: `workflow.py` `_estimate_plan_profile`/`_trap_move_sec`(사다리꼴 속도 프로파일 + `pre_cal=30 s` + `_CMD_OVERHEAD=0.055 s` + `_JOB_TIMING` 실측 보정 `0.55~1.85`), `#jobProgressWrap`/`#jobPercent`/`#jobEta`.
  6. **UI 선화·경로 생성 대기 `%` 및 EMA 예상 시간**: `.prepare_timing.json`(`0.65/0.35` EMA, 초기 `7.0 s`/`3.5 s`), `/api/health` `prepare_estimate`, `#prepareProgressWrap`/`#resultLoading`.
  7. **`mfl_ld` 전면 고정 및 전환 버튼 제거**: `pipeline_runner.py`·`server.py`·`launch_a4_app.bash` 기본 `mfl_ld` 고정, UI `#btnToggleMethod` 제거.
- **2026-11-19 14:27:39 ~ 14:29:40** (`9c45e5f0` #99~#100) **캘리그라피 가변 필압 Z 폭 확장(`+0.7 ~ -1.3 mm`) + `preview.svg` 가변 굵기 시각화**
  - `generator.py`: 최소 굵기 `0.0 → +0.7 mm`, 최대 굵기 `-1.0 → -1.3 mm` (총 Z 변화 폭 `2.0 mm`).
  - `svg_exporter.py`: `z_deltas_mm` 포함 획을 `0.35 ~ 1.95 mm`, `stroke-linecap="round"` 가변 선 굵기로 렌더링.
- **2026-11-19 14:33:06 ~ 14:42:42** `[DB/실기]` 고속화 첫 실기 시험(`7e077d1f`, `mfl_ld`, `detail=100.0`, `"Chiikawa!!"`, 230획 중 `168/230` 진행 시 `PEN_3` `stroke=169` 외력 CP#6 `Fx=+17.82 N`, X축 `10.9 mm` 밀림 → `RESUME` 후 `CANCEL` 중단) — 이 과정에서 조인트 과속 및 구불거리는 스플라인 부하를 체감하고 즉시 보완 착수.
- **2026-11-19 14:35:29 ~ 14:37:18** (`9c45e5f0` #101~#104) **조인트 속도 66.7% 감속 + 1~3번 펜 높이 `-0.2 mm` 최종 확정**
  - `joint_velocity`/`joint_acceleration`: `75.0 / 60.0 → 50.0` (`deg/s`, `deg/s²`).
  - 최종 `PEN_Z_OFFSETS`: `PEN_1` `12.0 → 11.8 mm`, `PEN_2` `12.5 → 12.3 mm`, `PEN_3` `13.0 → 12.8 mm`, `PEN_4` `12.5 mm` 유지 (**`[11.8, 12.3, 12.8, 12.5]`**).
- **2026-11-19 14:39:10** (`9c45e5f0` #105) **`movesx` 구불거리는 구간 하드웨어 보호 — 가변속 전환 및 곡률 기반 자동 감속 (`spline_motion_profile`)**
  - 스플라인 속도 옵션을 `DR_MVS_VEL_CONST`(`1`, 등속 강제) → **`DR_MVS_VEL_NONE`(`0`, 가변속)**으로 전환(`doosan_adapter.py`, `draw_image_standalone.py`, `equipment_settings.py`).
  - `stroke_executor.py`·`draw_image_standalone.py`·`workflow.py`(ETA 동기화)에 `spline_motion_profile()` 적용: 완만 곡선 상한 `0.85×`(`70.1 mm/s`), 허용 구심 가속도 `320.0 mm/s²`, S자 곡률 부호 반전(`reversals >= 2`) 추가 감속, 하한 `35.0 mm/s` / `80.0 mm/s²`.
- **2026-11-19 14:44:16 ~ 14:59:26** (`9c45e5f0` #106~#108) `#jobEta` 표시 최종 조정: 두 시간 의미 확인 → 전체 시간만 표시(`14:44:51`) → 남은 시간 복원 및 라벨 축약 **`남은 시간 약 X분 Y초 · 전체 시간 약 M분 S초`** (`14:58:59 ~ 14:59:26`).
- **2026-11-19 14:47:56 ~ 15:02:31** `[DB/실기]` **7번째 실기 완주 — 최종 튜닝 적용 완성작 실기 시연 성공!**
  - 작업 ID `cb1ed8e7`(`mfl_ld`, `detail=100`, `"Chiikawa!!"`, 220획: `PEN_1:59 / PEN_2:66 / PEN_3:76 / PEN_4:19`, 총 길이 `3,005.7 mm`, 가변 필압 `+0.7 ~ -1.3 mm`, 곡률 스플라인 감속, 최종 높이 `[11.8, 12.3, 12.8, 12.5]`): **`COMPLETED` (소요 875.3초 = 14분 35초)**.
- **2026-11-19 15:07:34 ~ 15:08:13** (`5c4f39b9` #27) + `[Git]` **`main` 동기화 커밋 `464c6ac`**
  - 커밋: `464c6ac9316d954a24bf73e82163b7f42d28b8dc` (`2026-11-19 15:08:11 +0900`, `HEAD -> bae, origin/main`, `Sync latest workspace state to main (kiosk workflow, path optimizer, controller, launch scripts)`, 23개 파일, +1,813 / -174줄, `.gitignore`에 `data/logs/` 추가).

### 15:09 ~ 16:51: 명화·영화 대사 실기 완주 2건, 복합 자모·마침표 보정, 슬라이더 즉시 취소 → 수동 `경로 추출` 전환, 다국어 정자체 및 새 PC 원클릭 배포 환경 구축

*(당일 후반 `A4`에서 **9회** 추가 `colcon build`(`16:11:36` ~ `16:49:19`) + 1회 `colcon list`(`16:40:18`), **14개** 신규 작업 생성, 실물 로봇 완주 **2건** 추가, 대화 `9c45e5f0` 10개 요청(#109~#118, 180스텝) 및 히스토리 정리 대화 `52b9f5b2` 진행; 같은 구간 `ws_dsr`과 `rokey_collaborate_1` 파일 변경은 0건.)*

- **2026-11-19 15:09:53** `[Git]` 팀원 `TW-94-git` (`origin/jang` HEAD) 커밋 **`014278b`** (`Merge remote-tracking branch 'origin/main' into jang` — 직전 `464c6ac` 동기화).
- **2026-11-19 15:10:36 ~ 15:34:08** (`52b9f5b2` 1차) **전체 프로젝트 히스토리 문서 `docs/PROJECT_HISTORY_KR.md` 최초 작성**
  - 사용자 요청(`15:10:36`, `15:11:09` 재전송)으로 `A4`, `ws_dsr`, `rokey_collaborate_1` 전체 파일·Git 커밋·과거 대화 22건·빌드·SQLite DB를 7개 구간 병렬 리서치 서브에이전트(`16b48e38`, `5021cd41`, `65cbafc5`, `92978b7f`, `d32a2921`, `d56b1ee1`, `fa081617`)로 전수 조사하여 `docs/PROJECT_HISTORY_KR.md`(776줄, 130,619 bytes, `15:33:45`) 최초 작성 완료.
- **2026-11-19 15:20:59 ~ 15:41:49** `[작업로그/DB/실기]` **8번째 실기 완주 — 『뭉크의 절규』 + 한글 붓글씨 실기 시연 성공!**
  - `15:20:59 ~ 15:21:54`: `8528e3e1`(`pictures/뭉크의 절규.jpg`, `479×641`, `mfl_ld`, `detail=50.0`, 문구 없음, 356획) 1차 미리보기 생성.
  - `15:21:10 ~ 15:22:48`: `4d7c6b73`(`8528e3e1` 선화 재사용, 문구 **`"우으어어어어어"`**, 327획: `PEN_1:98 / PEN_2:112 / PEN_3:97 / PEN_4:20`, `z_deltas_mm=True`) 승인 및 실행.
  - `15:22:48 ~ 15:41:49`: **`COMPLETED` (327/327획, 소요 1,140.9초 = 19분 1초)**.
- **2026-11-19 15:46:19 ~ 16:02:11** `[작업로그/DB/실기]` **9번째 실기 완주 — 『죽기 딱 좋은 날씨네』 + 장문 한글 붓글씨 실기 시연 성공!**
  - `15:46:19 ~ 15:47:48`: `pictures/죽기 딱 좋은 날씨네.png`(`480×360`, `mfl_ld`) 4연속 프리뷰 조정:
    - `e1d2f2b1` (`detail=50.0`, `"우으어어어어어"`, 118획)
    - `5ce5d85d` (선화 재사용, **`"죽기 딱 좋은 날씨네~ 담배 좀 줘라"`**, 157획, `PEN_4:59`)
    - `3ae9e5e9` (`detail=100.0`, `"죽기 딱 좋은 날씨네~ 담배 좀 줘라"`, 205획)
    - `3b83abc6` (`detail=77.0`, `"죽기 딱 좋은 날씨네~ 담배 좀 줘라"`, 204획: `PEN_1:49 / PEN_2:49 / PEN_3:47 / PEN_4:59`, `z_deltas_mm=True`) 승인 및 실행.
  - `15:47:58 ~ 16:02:11`: **`COMPLETED` (204/204획, 소요 853.3초 = 14분 13초)**. 이 결과물에서 `"줘"`의 `ㅈ` 윗획·`ㅝ` 가운데 가로획 결손을 발견해 바로 다음 개선으로 이어짐.
- **2026-11-19 16:09:57 ~ 16:15:22** (`9c45e5f0` #109~#112) **복합 한글 자모(`ㅈ`, `ㅝ`, `줘`) 교차 획 결손 해결 및 불필요 필터 제거**
  - `16:09:57 ~ 16:11:56` (#109): `"ㅈ"`, `"ㅝ"`, `"줘"` 직접 렌더링 디버깅 결과 3가지 원인 규명 — ① 픽셀 `visited` 추적 시 교차점 사이 `ㅝ`의 `ㅓ` 가운데 가로획 탈락, ② `_prune_spurs(max_spur_len=6)`이 `ㅈ` 시작 획을 잔가지로 절단, ③ `slen >= 15.0 px` 필터가 정식 짧은 획 삭제.
    - 수정(`calligraphy/generator.py`): 8방향 중복 대각선 제거 후 **엣지(간선) 기반 추적(`used_edges`, 직진성 `cos >= 0.60`)**으로 전면 교체, `max_spur_len=2` 및 `slen >= 8.0 px` 완화 → `"줘"` `4획 → 6획`(`ㅈ` 2 + `ㅜ` 2 + `ㅓ` 2) 복구(`16:11:36` `art_artwork_pipeline` 빌드).
  - `16:13:07 ~ 16:13:33` (#110): 사용자 지적("글자를 쓸 때는 애초에 잔가지 제거·짧은 획 필터가 없으면 더 간단하겠다") 반영 → 폰트 마스크에는 사진 노이즈가 없으므로 `_prune_spurs` 호출과 `slen >= 8.0` 필터 완전 제거(`16:13:31` 빌드, `'ㅈ'` 2획·`'ㅝ'` 4획·`'줘'` 6획·`'안녕 Hello ★!'` 19획 검증).
  - `16:14:40 ~ 16:15:22` (#111~#112): 실제 필기 획 순서·개수 유사도 확인(`_render_text_ordered` `x + 0.85 * y` 정렬 + `_orient_human_stroke`, 붓글씨 연필/교차 특성 안내) 및 사용자 감사 인사.
- **2026-11-19 16:15:50 ~ 16:21:28** `[작업로그]` `Im_Gatsby.png`(`1024×446` 정규화, `mfl_ld`) 4연속 프리뷰 테스트 — `218712ae`(`detail=77`, `"죽기 딱 좋은 날씨네~ 담배 좀 줘라"`, 421획), `80138cde`(`detail=100`, **`"I'm Gatsby."`**, 376획, `PEN_4:15`), `e1a66ea4`(`detail=48`, `"I'm Gatsby."`, 340획), `b14c1e7d`(`detail=50`, `"I'm Gatsby."`, 340획). 슬라이더 이동 대기 시간과 `"."` 마침표 누락을 체감함.
- **2026-11-19 16:20:09 ~ 16:22:18** (`9c45e5f0` #113) **선화·경로 최적화 중 슬라이더 변경 시 즉시 취소 및 재시작 구현**
  - 수정 파일: `art_kiosk/static/app.js`(`AbortController` + `/api/kiosk/prepare/cancel` + 0.4초 디바운스), `art_kiosk/workflow.py`(`/api/kiosk/prepare/cancel` 신설, 이전 `PREPARING` 자동 취소 후 `.processing` 해제 대기, 동일 `_lineart_bucket` `low`/`medium`/`high` 구간 선화 재사용), `art_kiosk_bridge/{http_api.py, bridge_node.py}`(`/bridge/artwork/cancel` → ROS 2 Action `cancel_goal_async()`), `art_artwork_pipeline/{pipeline_runner.py, pipeline_node.py}`(`mfl_ld` 서브프로세스 0.1초 주기 취소 감시 `terminate()`, 직전 취소 직후 최대 3초 잠금 대기).
  - 빌드 (`16:22:13`): `art_artwork_pipeline`, `art_kiosk_bridge`, `art_kiosk` 3패키지 빌드·검증 완료.
- **2026-11-19 16:22:54 ~ 16:24:35** (`9c45e5f0` #114) **마침표(`.`)·문장부호 점 누락 수정 및 준비 중 남은 시간 표시 제거**
  - 원인: `.`은 짧은 획(`~1 mm`)이라 끝점이 `+0.7 mm`로 들려 종이에 닿지 않고, `!`/`?`/`:` 아래 점은 세선화 시 1 px 단독 점(`isolated`) 또는 6 px 미만으로 탈락함.
  - 수정(`calligraphy/generator.py`): `isolated` 점 및 충분한 마스크 면적의 짧은 점 획(`is_valid_dot`) 유지, `2.5 mm` 미만 짧은 점은 종이 위로 뜨지 않게 `z_deltas_mm <= -0.3 mm`로 눌러 찍도록 수정(`.`: 1획, `!`/`?`/`:`/`;`/`i`/`j`: 2획, `안녕.`: 9획 검증).
  - UI 수정(`art_kiosk/static/{index.html, app.js}`): 선화·경로 준비 중 표시되던 `#prepareEta` 및 `... 남음` 제거(로봇 그리기 `남은 시간 · 전체 시간`은 유지).
  - 빌드: `16:24:06`(`art_artwork_pipeline`, `art_kiosk`), `16:24:33`(`art_artwork_pipeline`).
- **2026-11-19 16:27:38 ~ 16:37:11** `[파일/작업로그]` **`pictures/렌고쿠.jpeg` 추가, 일본어 `"心を燃やせ"` 테스트 및 로딩바·409·504 이슈 발견**
  - `16:27:38`: `pictures/렌고쿠.jpeg` (`596×335`, 45,982 bytes) 추가.
  - `16:28:35 ~ 16:28:41`: `4a0cd707` (`렌고쿠.jpeg`, `mfl_ld`, `detail=50.0`, **`"心を燃やせ"`**, `LINEART` 단계 중단).
  - `16:29:22 ~ 16:29:53` (`9c45e5f0` #115): 사용자 보고("선화 로딩바는 초기화가 안되네.") → 원인(`stopPrepareUi(false)`가 `value`/`%`를 `0%`로 초기화하지 않았고 `pollCurrent()`가 취소된 이전 요청 진행률을 재표시함) 수정(`app.js` `prepare_request_id === state.inflightRequestId` 일치 시에만 반영, `16:29:51` `art_kiosk` 빌드).
  - `16:34:40 ~ 16:37:11`: `렌고쿠.jpeg` 연속 슬라이더 이동 테스트 3건(`6248d0c2`, `81189fb2` 사진 단계 즉시 취소 → `9dc26219` `detail=99.0`, `"心を燃やせ"`, `.prepare_timing.json` `lineart_sec=6.78, plan_sec=49.4` 갱신) 중 `art_system.log`에 `POST /api/kiosk/prepare 409 Conflict` 발생 및 `16:35:26` 앱 종료, `16:37:11` `.current_workflow.json`에 `504: 이미지 처리 응답 시간 초과입니다`(`UNKNOWN_PREPARATION`) 기록.
- **2026-11-19 16:32:13 ~ 16:49:27** (`9c45e5f0` #116~#118) **3대 완성도 개선 일괄 구현 — 새 PC 원클릭 배포 환경 + 수동 `경로 추출` 버튼 + 다국어 정자체 따라 그리기**
  - `16:32:13 ~ 16:34:21` (#116~#117): 다른 PC 배포 시 누락 요소(`NanumBrush.ttf`, `a4-lineart` 가상환경, `face_landmarker.task`, 시스템/ROS 패키지, 절대경로 `.desktop`) 진단 → Docker 대신 **폰트 저장소 내장 + `scripts/setup_env.bash` 원클릭 설치 스크립트** 조합 확정.
  - `16:37:13 ~ 16:49:27` (#118): 사전 환경 감사(`colcon list` `16:40:18`, HarfBuzz `raqm`·`ximgproc`·`vendor/rg2` 확인) 후 3개 요구사항 및 잠재 버그 일괄 반영:
    1. **원클릭 배포 환경 구축**:
       - `assets/fonts/NanumBrush.ttf` (3,745,376 bytes, `16:42:16`) 저장소 내장 및 `generator.py` 1순위 등록.
       - **`scripts/setup_env.bash`** (201줄, `16:42:42`) 신설: `--skip-apt`/`--skip-dl`/`--skip-build` 옵션 지원, 시스템·다국어 폰트(`fonts-nanum`, `fonts-noto-cjk`, `fonts-noto-core`, `fonts-dejavu-core`, `libraqm0`)·Python 웹 패키지·`a4-lineart` CPU PyTorch 가상환경·`face_landmarker.task` 자동 다운로드·`rosdep`/`colcon build`·현재 경로 기준 `A4_Drawing.desktop` 등록·최종 자체 점검까지 1회 실행으로 완결.
       - `scripts/launch_a4_app.bash` (`16:43:03`): 실행 전 환경 사전 점검(누락 시 `setup_env.bash` 안내), 별도 `ws_dsr` 없는 PC에서 `vendor` 드라이버(`ros2_ws/install`) 자동 폴백, Chrome 미설치 시 Chromium 폴백 추가.
       - `/home/qownsdud/Desktop/A4_Drawing.desktop` (`16:49:23`) 최신 갱신 및 `./scripts/setup_env.bash --skip-apt --skip-dl --skip-build` 자체 점검 통과.
    2. **수동 `경로 추출` 버튼(`#btnExtract`) 전환 및 `.workflow.lock` 경합(`409`) 해결**:
       - `art_kiosk/static/{index.html, style.css, app.js}` (`16:45:26 ~ 16:45:35`): 사진 촬영·업로드, 문구 입력, 슬라이더 이동 시 자동 변환을 제거하고 **`경로 추출` (`#btnExtract`)** 버튼을 눌러야 변환 시작. 설정 변경 시 기존 미리보기·`그리기` 버튼 즉시 잠금 및 진행 중 추출 취소.
       - `art_kiosk/workflow.py` (`16:46:18`): 직전 추출 도중 설정 변경 후 즉시 재추출 시 `.workflow.lock` 미해제로 `409 Conflict`가 발생하던 경합 조건을 `acquire_workflow_lock`(사전 취소 신호 + 최대 `3.5초` 잠금 대기)으로 해결.
    3. **붓글씨 미지원 다국어 정자체 따라 그리기 (`calligraphy/generator.py` +420줄, `svg_exporter.py`)**:
       - `NotoSans-Regular`, `NotoSansCJK-Regular`, `DejaVuSans` 및 `fontconfig`(`fc-match`/`fc-list`) 동적 탐색으로 일본어·중국어·러시아어·그리스어·태국어·아랍어·힌디어·유럽 악센트 문자 지원.
       - **잠재 버그 3건 사전 해결**: ① **`_has_visible_glyph`** 도입으로 `NanumBrush.ttf`에 코드포인트만 있고 픽셀이 비어 한자(`愛`, `好`, `世`, `界`)가 빈칸으로 빠지던 현상 방지, ② **`is_brush` 분리**로 정자체 언어는 가변 필압 대신 **균일 높이(`0.0 mm`, 짧은 점 `-0.3 mm`)**로 깔끔히 그리기(한글·영문 붓글씨는 `+0.7 ~ -1.3 mm` 유지), ③ **HarfBuzz(`raqm`) 셰이핑**으로 태국어·힌디어 결합 부호/합자(`สวัสดี`, `नमस्ते`)·아랍어 연결어(`مرحبا`) 잘림 방지 및 세선화 시 소실되는 대칭 원형 점(`Ü`, `Ö`, `Ä`, 아랍어 `ش`) 중심점 자동 복구.
       - 빌드 (`16:46:40`, `16:48:15`, `16:49:19`) 및 다국어 시각화 검증(`안녕! 줘.` 17획, `こんにちは 愛` 27획, `你好世界` 26획, `Привет` 10획, `Γεια σου` 9획, `สวัสดี` 10획, `مرحبا` 6획, `नमस्ते` 13획, `Ü`/`Ö`/`Ä`/`ش`) 전부 통과. *(참고: `16:09 ~ 16:49` 변경분 11개 수정 파일 + `assets/`·`scripts/setup_env.bash`·`pictures/렌고쿠.jpeg`·`docs/PROJECT_HISTORY_KR.md`는 `16:51` 시점 로컬 워킹 트리에 반영 완료, 미커밋 상태.)*

---

## 8장. 부록 — 정량 아카이브 및 최종 확정 파라미터 총람

### 8.1 Antigravity 대화 전체 인덱스 (총 23건)

1. **`5efb50cd`** (`2026-11-13 10:19:58 ~ 10:35:43`, 16 스텝 / 3 요청): `아이디어.txt` AI 실현성 검토, 사양서 3종 작성(`specificationn` → `specification`).
2. **`39951373`** (`2026-11-13 10:39:24 ~ 11-17 17:37:23`, 102 스텝 / 9 요청): 옵션 A 클라우드 API 설계, Canny 전환·문서 갱신, 11/17 `rokey_collaborate_1` 전수 점검(`=0.0.9`/`=1.0.0` 삭제).
3. **`194ddcd7`** (`2026-11-13 11:10:12 ~ 11:18:02`, 43 스텝 / 2 요청): `전체_업무_파이프라인.txt` 초안 및 전체 대화·매뉴얼 4종 통합 재작성.
4. **`1eeef029`** (`2026-11-13 11:27:17 ~ 11-17 16:08:13`, 186 스텝 / 14 요청): Phase 1 키오스크 구축, Cloudflare 429 대응, 로컬 DL 3단계, `lineart_onetouch`, 카메라+DL 확정, 11/17 A4 가로 2 cm 여백 개편.
5. **`eca9173a`** (`2026-11-13 11:27:55 ~ 16:42:45`, 114 스텝 / 12 요청): Phase 3 `phase3_path_planner` v1~v4 구현·튜닝 및 `history/` 자동 아카이브.
6. **`4f91a1ce`** (`2026-11-13 11:28:31 ~ 11:28:52`, 14 스텝 / 1 요청): Phase 4 ROS 2 로봇 드로잉 제어 킥오프.
7. **`6d804672`** (`2026-11-13 11:28:41 ~ 11:28:58`, 11 스텝 / 1 요청): Phase 5 안전·예외·상태 머신 킥오프.
8. **`5d83d589`** (`2026-11-13 14:15:15 ~ 11-17 17:34:11`, 159 스텝 / 21 요청): 사진 기반 `phase2_lib_lineart` 구축·잔선 튜닝 확정, 11/17 MediaPipe `0.10.21` 하이브리드 `lineart_mfl_ld.py` v1~v4 개발·확정.
9. **`a35129b6`** (`2026-11-13 14:28:11 ~ 14:35:28`, 16 스텝 / 1 요청): YAML 기반 `file_manager.py`·`test_file_manager.py`·`files.yaml` 제작.
10. **`a73748f9`** (`2026-11-13 17:43:38 ~ 11-17 17:46:44`, 122 스텝 / 10 요청): GitHub `qownsdud/A4` 초기 업로드(`a8c6e4b`), 11/16 `main` 원복(`b1bcf16`), 11/17 `ws_dsr` 정리 및 `bae` 푸시(`82ca6eb`).
11. **`e109e205`** (`2026-11-14 13:04:49 ~ 11-17 17:41:13`, 489 스텝 / 70 요청): 11/14 실기 순응/힘 제어 집중 실험·SVG 드로잉·자동 힘 탐색, 11/17 `draw_image_standalone.py` 생성·빈 그리퍼 9점 재측정·`--virtual`·`ws_dsr` 감사·`sub` 브랜치 푸시(`6e0ef9e`).
12. **`842be4dd`** (`2026-11-16 09:54:09 ~ 11-17 11:54:29`, 649 스텝 / 82 요청): `collaborate1` 정리, `pentest` 통합, Pylance, `draw1`/`draw_routes`/`cursive_font`, 9점 캘리브레이션, 펜·막대 티칭, 1~14단계 `draw_multi_pen`, `run_logger`, 서브모듈+`registry.yaml`, `image_vectorizer`+`draw_image_multi_pen`, 11/17 단일 `art` 패키지 및 JSON 업로드.
13. **`3040210a`** (`2026-11-17 09:49:07 ~ 11-18 12:26:38`, 35 스텝 / 7 요청): FastDDS `.bashrc` 정리 및 Wi-Fi AP Isolation 진단, 11/18 `ryu/src/calligraphy` 다운로드.
14. **`22979593`** (`2026-11-17 12:27:27 ~ 16:57:10`, 317 스텝 / 28 요청): RViz TF `.bashrc` 해결, 기준 막대 `-45°` 회전, `x` 중단 복귀, 0.5→0.1 mm 2단 하강, 4 cm 여백, 그리퍼 재정렬, 직접 벡터화+프리뷰 백업, `draw_height_test`, `movesx`/`movel` 35° 하이브리드, `MORPH_CLOSE` 제거, `bae`/`main` 동기화.
15. **`8b1ba7aa`** (`2026-11-17 17:54:52 ~ 18:39:49`, 56 스텝 / 7 요청) & **`a47eb03c`** (`17:58:06 ~ 18:05:10`, 69 스텝, 브라우저 서브에이전트): Notion `10기 A4 퍼즐 드로잉 로봇` 11개 페이지 전수 조사 및 통합 워크스페이스 `/home/qownsdud/ws_cobot_pjt/A4` 창설.
16. **`5c4f39b9`** (`2026-11-17 18:50:02 ~ 11-19 15:08:13`, 274 스텝 / 27 요청) & **`db78db5e`** (`18:57:53 ~ 19:01:04`, 31 스텝, 브라우저 서브에이전트): `yongsoo` 압축해제, 안전 잠금 제거·`back/` 분리, `travel_z_mm`·속도 수정, 11/18~11/19 `bae`·`main` 7연속 커밋(`f00e4d6` ~ `464c6ac`).
17. **`ba08c363`** (`2026-11-17 19:27:14 ~ 11-19 10:03:07`, 1,076 스텝 / 93 요청): `draw_image_standalone` 이식, `SetCurrentTool`·`RECOVERY_REQUIRED` 제거, `vendor/`·`config/` 완전 독립화, SQLite 분리 `art_job_manager` 신규 구현, `SQLITE_SIGNAL_CONTRACT_KR.md`, `origin/jang`·`origin/yongsoo` 이식, 실기 9연전 디버깅 및 속도 상향.
18. **`9c45e5f0`** (`2026-11-17 19:47:57 ~ 11-19 16:49:27`, 1,391 스텝 / 118 요청 + 아티팩트 `lineart_comparison.md`): `control/` 분리, `standalone_drawer` 직결, `futex_do_wait` 수정, `art_state_store` 정식 패키지화, TCP `-230 mm` 보정, 한글 캘리그라피·`NanumBrush.ttf`, `PEN_4`, `test_stick_and_pens.py`, `PEN_3` 11단계 튜닝, 데스크톱 앱 `A4 Drawing Studio`, 가변 필압·사람 필순·7대 최적화·곡률 스플라인 감속·ETA UI, 후반 `ㅈ`/`ㅝ`/`.` 보정·슬라이더 즉시 취소 → 수동 `경로 추출` 전환·다국어 정자체·`setup_env.bash` 원클릭 배포 환경 구축.
19. **`bb64c38c`** (`2026-11-18 15:31:06 ~ 16:08:30`, 205 스텝 / 17 요청): RGB 3색 균일·랜덤 배정, `55 mm` 분할·`connected_pairs` 동색 재병합 차단, 개츠비 GrabCut 인물 분리 및 배경 큰 윤곽선 보존.
20. **`df415475`** (`2026-11-18 20:01:42 ~ 20:01:49`, 4 스텝 / 1 요청): 다른 노트북 RViz `base_link` TF 누락 오류 4단계 진단 안내.
21. **`52b9f5b2`** (`2026-11-19 15:10:36 ~ 16:51+`, 현재 대화 및 7개 병렬 리서치 서브에이전트): 전체 프로젝트 히스토리 문서 `docs/PROJECT_HISTORY_KR.md` 최초 작성 및 최신화.

### 8.2 Git 전 브랜치 계보 및 팀원별 기여 요약 (`https://github.com/qownsdud/A4`)

- **`qownsdud` (`main`, `bae`, `sub`, `yongsoo` 초기)**
  - 담당: 초기 기획·Phase 1~3·`rokey_collaborate_1`(`a8c6e4b`, `b1bcf16`, `ae23c52`, `6e0ef9e`), 실물 로봇 제어·캘리브레이션·멀티펜·벡터화·`draw_image_standalone`(`86d9e7a`~`82ca6eb`), `yongsoo` ROS 2 7패키지 통합 및 `AGENTS.md`(`4decdd9`~`5a3ecfd`), 최종 통합 `A4` 워크스페이스·`vendor/` 독립화·`JobManager`·RGB 다양화·한글 캘리그라피·`PEN_4`·데스크톱 앱·고속 스플라인·`main` 동기화(`f00e4d6`~`464c6ac`), 이후 로컬 워킹 트리에서 복합 자모/마침표 보정·수동 `경로 추출`·다국어 정자체·`setup_env.bash` 원클릭 배포 환경 완성.
- **`TW-94-git` / `jtw` (`origin/jang` 브랜치)**
  - 담당: A4 오프라인 경로 계획·3색 그룹화 최적화(`b0e00eb`, `66c3956`), `run_full_pipeline.py`(`a7246ce`), 실측 9점 좌표 기반 로봇 좌표 변환·시뮬레이션(`3a82590`~`a7eccd7`), Haar Cascade 얼굴 ROI 선화 및 Balanced 경로 계획(`c1cba16`), 0~100 슬라이더 CV 밀도 보간(`e7524ac`), 11/19 `bae`/`main` 최신 병합 동기화(`34ae5d9`, `0b44d8d`, `014278b`).
- **`RyuM-S` (`origin/ryu` 브랜치)**
  - 담당: 붓펜 보호·외력 단위 테스트 `pentest` 패키지(`96631e4`), 한글 캘리그라피 `calligraphy_path_gen.py`/`draw_calligraphy.py` 및 `pen_height_calibration.py`(`4bb08dd`, `bb49dd9`, `9d3a896`), 독립 SQLite 상태·외력 복구 웨이포인트 저장소 `art_state_store`(`43418d8`).
- **`dduter` (`origin/yongsoo` HEAD)**
  - 담당: 통합 UI(`/admin` 307 리다이렉트, `0~100` 슬라이더, 제어 버튼, 외력 배너) 및 실시간 관측·예외처리·체크포인트 복구(`bc2f32c`, 141 pytest 통과).

### 8.3 실물 로봇 완주 및 주요 실행 기록 총람

#### `ws_dsr/run_logs/` 실물 실행 로그 (총 6건, 완주 4건)

- **1차** (`2026-11-16 18:53:46 ~ 18:57:16`, 3분 30초): `draw_multi_pen` 1~14단계 최초 완주(바닥 `317.66 mm`, 정사각형·정삼각형·원).
- **2차** (`2026-11-16 19:02:36 ~ 19:02:39`, 3초): 시작 직후 중단.
- **3차** (`2026-11-16 19:02:41 ~ 19:06:14`, 3분 33초): `draw_multi_pen` 2차 완주(바닥 `317.67 mm`, `0.01 mm` 반복 정밀도 검증).
- **4차** (`2026-11-16 21:29:07`, 0초): `test_image_strokes.json` `FileNotFoundError` 종료.
- **5차** (`2026-11-16 21:32:24 ~ 21:54:53`, 22분 29초): `draw_image_multi_pen` **최초 3펜 분할 인물화 실물 완주**(382획/857점, 바닥 `317.66 mm`).
- **6차** (`2026-11-17 12:46:46 ~ 13:09:15`, 22분 29초): `draw_image_multi_pen` 개선본 **2차 3펜 인물화 완주**(214획/1,177점, 바닥 `317.66 mm`).

#### `A4/data/art_state.db` 실물 완주 9건 요약 (총 28건 실행 중 `COMPLETED` 9 / `STOPPED` 15 / `RECOVERY_REQUIRED` 3 / `FORCE_STOPPED` 1; `job_events` 2,325건(`STROKE_COMPLETED` 2,140건), `command_receipts` 37건)

1. **`60dbe6cf`** (`2026-11-18 14:39:31 ~ 14:49:52`, **10분 22초**): `cv`, `"AAAA"`, 66획(`PEN_1~3`), TCP `-230 mm` 보정 직후 **A4 통합 최초 완주**.
2. **`c135a9f2`** (`2026-11-18 15:18:35 ~ 15:38:11`, **19분 35초**): `cv`, `detail=100.0`, `"AAAA"`, 105획(`PEN_1~3`).
3. **`74add98f`** (`2026-11-18 16:14:18 ~ 16:46:48`, **32분 30초**): `cv`, `detail=50.0`, `"Im Gatsby"`, 171획(`63/55/53`), **개츠비 RGB 균일 배정 + GrabCut 첫 완주**.
4. **`7d9e0245`** (`2026-11-18 18:34:41 ~ 18:43:37`, **8분 55초**): `cv`, `"A Moo Geo Na"`, 64/64획(`28/18/18`), **`ros` 컨트롤러 첫 전획 완주**.
5. **`0ca1f525`** (`2026-11-19 12:33:52 ~ 13:07:15`, **33분 22초**): `mfl_ld`, `"AAAA - 퍼즐 드로잉!"`, 329/329획(`99/98/99/33`), **`mfl_ld` + 4색 `PEN_4`(한글 붓글씨) 첫 완주**.
6. **`d415974e`** (`2026-11-19 13:13:02 ~ 13:55:40`, **42분 38초**): `mfl_ld`, `detail=100.0`, `"A4 - 퍼즐 드로잉!"`, 417/417획(`130/131/130/26`), **가변 필압 붓글씨 + 최장 417획 완주**.
7. **`cb1ed8e7`** (`2026-11-19 14:47:56 ~ 15:02:31`, **14분 35초**): `mfl_ld`, `detail=100`, `"Chiikawa!!"`, 220/220획(`59/66/76/19`, 총 길이 `3,005.7 mm`), **고속 스플라인 최종 튜닝 시연 완주**.
8. **`4d7c6b73`** (`2026-11-19 15:22:48 ~ 15:41:49`, **19분 1초**): `mfl_ld`, `뭉크의 절규.jpg`, `"우으어어어어어"`, 327/327획(`98/112/97/20`, 가변 필압), **명화+한글 붓글씨 완주**.
9. **`3b83abc6`** (`2026-11-19 15:47:58 ~ 16:02:11`, **14분 13초**): `mfl_ld`, `detail=77.0`, `죽기 딱 좋은 날씨네.png`, `"죽기 딱 좋은 날씨네~ 담배 좀 줘라"`, 204/204획(`49/49/47/59`, 가변 필압), **장문 한글 붓글씨 완주**.

#### 외력 감지 복구 체크포인트(`recovery_checkpoints`, 총 6건)

- **CP#1** (`11/18 17:18:50`, `665e5402`): `stroke=0`, `Fz=+14.73 N` (초기 `15 N` 공중 오탐 → `20 N` 상향 계기).
- **CP#2** (`11/18 18:22:57`, `79382622`): `PEN_1`, `stroke=1, pt=4`, `Fx=+11.14 / Fy=-16.76 N`(수평 ~20.1 N) → `18:23:08 RESUME` 재개 성공.
- **CP#3** (`11/18 18:24:40`, `79382622`): `PEN_1`, `stroke=2, pt=1`, `force=[12.53, -11.67, 13.42 N]`.
- **CP#4** (`11/18 18:28:02`, `7d869849`): `stroke=0`, `force=[21.62, -28.95, 26.00 N]` → `CANCEL` 도구 반납·홈 복귀 검증.
- **CP#5** (`11/18 19:25:17`, `e6394e0a`): `PEN_1`, `stroke=318`, `Fx=-25.24 N` → 안전 반납.
- **CP#6** (`11/19 14:41:59`, `7e077d1f`): `PEN_3`, `stroke=169, pt=1`, `Fx=+17.82 / Fy=-11.09 N` (X축 `10.9 mm` 밀림 감지).

### 8.4 `A4` 작업(267건) 및 `colcon build`(445회) 정량 통계

- **작업 분포(총 267건: `data/jobs` 254 + `back/data/jobs` 13)**
  - 일자별: 11/17 **24건** / 11/18 **130건** / 11/19 **113건**
  - 엔진별: `cv` **225건** / `mfl_ld` **40건**(11/19 `12:24` 이후 전면 전환) / 사진 단계 취소(`PHOTO_ONLY`) **2건**
  - 상태별: `PREPARED` **238건** / `LINEART` 중단 **27건**(11/18 초기 유니코드 시험 25건 + 11/19 일본어 `렌고쿠.jpeg` 시험 2건) / `PHOTO_ONLY` **2건**
  - 승인·특성: `approved=True` **38건**, 캘리그라피 포함 **187건**, `PEN_4` 사용 **66건**, 가변 필압 `z_deltas_mm` 포함 **25건**, 전체 누적 획 **36,938획**(평균 `155.2획`, 최소 `37획`, 최대 `1,021획`)
- **`colcon build` 총 445회 추이**
  - `ws_dsr` **349회**: 11/12 **155회** / 11/14 **81회** / 11/16 **62회** / 11/17 **50회** (외 최신 링크 1)
  - `A4` **96회(실패 0회)**: 11/17 **19회**(7패키지 → 5패키지) / 11/18 **42회**(14패키지 `vendor/` 편입 → 17패키지 풀 워크스페이스 완성) / 11/19 **35회**(4펜·데스크톱 앱·고속 스플라인 26회 + 16시대 자모/마침표·수동 추출·다국어 정자체 9회, 별도 `colcon list` 1회)

### 8.5 최종 확정 시스템 파라미터 총람 (`2026-11-19 16:51`, 로컬 최신 워킹 트리 기준)

- **로봇·그리퍼·기준 설정**
  - 하드웨어: `robot_id="dsr01"`, `robot_model="m0609"`, `tool_name="Tool_Weight"`, `tcp_name="GripperDA_v1"` (`TCP Z = 230.0 mm`), RG2 `grip_output=1`, `release_output=2`
  - 자세: `HOME_JOINTS = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]`, `READY_OFFSET = [0.0, 0.0, -100.0, 0.0, 0.0, 0.0]`
  - 9점 바닥 평면 (`config/plane_calibration.json`): `a = 0.002184`, `b = -9.913e-05`, `c = 7.340 mm`, `tilt_deg = 0.125°`, `flatness_pv_mm = 0.533 mm`, `rmse_mm = 0.189 mm`, `auto_calibrate_9pt = False`
  - 기준 막대 (`config/stick_slot.json`): `[583.354, -36.316, 136.725, 90.267, 179.978, 90.632]`, 파지 회전 `STICK_GRIP_RZ_OFFSET_DEG = -45.0°`
  - 펜 4슬롯 (`config/pen_slots.json`):
    - `PEN_1` (Red `#e53935`): `[567.362, 42.678, 136.732, 90.297, 179.978, 90.663]`, `z_offset_mm = 11.8 mm`
    - `PEN_2` (Green `#2e7d32`): `[567.467, 11.279, 136.716, 95.006, 179.978, 95.372]`, `z_offset_mm = 12.3 mm`
    - `PEN_3` (Blue `#1565c0`): `[567.959, -19.422, 136.728, 92.305, 179.978, 92.671]`, `z_offset_mm = 12.8 mm`
    - `PEN_4` (Black `#111111`, 캘리그라피): `[567.470, 78.250, 136.730, 10.810, -178.990, 10.780]`, `z_offset_mm = 12.5 mm`
- **모션 속도·가속도·스플라인·안전 보호**
  - 속도/가속도: `joint = 50.0 / 50.0`, `travel = 150.0 / 220.0`, `draw (movel) = 82.5 / 200.0`, `pen_down = 65.0 / 180.0`, `pick = 40.0 / 80.0`, `probe = 5.0 / 5.0`
  - 리프트·접근: `stroke_lift_mm = 4.0`, `group_lift_mm = 15.0`, `slot_approach_mm = 100.0`
  - 스플라인 보호: `use_spline = True`, `spline_max_points = 80`, `spline_vel_opt = 0` (`DR_MVS_VEL_NONE`), `spline_vel_scale = 0.85` (`70.1 mm/s`), `spline_max_lateral_acc = 320.0 mm/s²`, `spline_min_velocity = 35.0 mm/s`, `spline_min_acceleration = 80.0 mm/s²`, `corner_angle_deg = 55.0°`, `CORNER_MIN_ARM_MM = 1.2 mm`, 완료 폴링 `5 ms`
  - 외력·서보 보호: `external_force_limit_n = 20.0 N`, 정지/도달 허용치 `2.0 mm / 2.0°` · `1.0 mm/s`, 바닥 접촉 탐색 `0.5 mm → 0.1 mm`, `CONTACT_FORCE_DELTA_N = 2.5 N`, `HARD_LIMIT_FORCE_N = 60.0 N`
- **선화·경로 최적화·다국어 캘리그라피·키오스크 UI·원클릭 배포**
  - 선화 엔진: `mfl_ld` 전면 고정 (`~/.venvs/a4-lineart`, `~/.cache/a4/models/face_landmarker.task`)
  - 키오스크 워크플로우: 수동 **`경로 추출` (`#btnExtract`)** 트리거, 설정 변경 시 이전 작업 즉시 취소(`/api/kiosk/prepare/cancel`, `/bridge/artwork/cancel`, `acquire_workflow_lock` 최대 3.5초 대기), 준비 중 `%`만 표시(로봇 그리기 시 `남은 시간 · 전체 시간` 유지)
  - RGB 색 다양화: `assign_stroke_pens`(`neighbor_k=3`, 누적 길이 균형) + `split_long_stroke(max_length_mm=55.0)` + `connected_pairs` 동색 재병합 차단
  - 잉크 번짐 방지: `simplify_tolerance_mm = 0.22`, `min_point_spacing_mm = 0.85`, `min_stroke_mm = 2.5`, `max_ink_passes = 1`, `cell_mm = 0.5`, `patch_mm = 3.0`, `max_local_ink_mm = 6.5`, `allow_cross_mm = 1.8`
  - 캘리그라피·다국어 정자체: 1순위 저장소 내장 `assets/fonts/NanumBrush.ttf` + 다국어 `NotoSans`/`NotoSansCJK`/`DejaVuSans`/`fontconfig` 동적 폴백(`_has_visible_glyph` 빈 한자 차단, HarfBuzz `raqm` 셰이핑, 엣지 추적 `used_edges`, 대칭 원형 점 중심 복구), 가로 영역 `50.0 ~ 247.0 mm`(좌측 정렬), `height_mm = 16.0 mm`, `maxlength = 20`, 사람 필순 정규화(`_orient_human_stroke`), 붓글씨 가변 Z 필압 `+0.7 mm ~ -1.3 mm` / 정자체 균일 높이 `0.0 mm` / `2.5 mm` 미만 짧은 점 `<= -0.3 mm`, `preview.svg` 선 굵기 `0.35 ~ 1.95 mm`
  - 원클릭 설치·실행: `./scripts/setup_env.bash`(새 PC 1회 설치·자체 점검) → `/home/qownsdud/Desktop/A4_Drawing.desktop` → `scripts/launch_a4_app.bash` (환경 사전 점검 → `sodreal`(`vendor` 자동 폴백) → `art_system.launch.py` 5노드 + `art_state_store` → Chrome/Chromium `--app` 창 + 종료 시 자동 정리)
