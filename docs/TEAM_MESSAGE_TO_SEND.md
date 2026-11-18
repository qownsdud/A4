# 팀원 공유 메시지 (복사하여 전송)

이번에 A4 ROS 2 통합 코드의 주석과 문서를 정리하고, 실행 이름을 통일했습니다.

- 운영형 JobManager: `ros2 run art_job_manager job_manager` (기존 실제 Action Client 코드)
- 시험용 시뮬레이션: `ART_JOB_SIMULATE=1 ros2 run art_job_manager job_manager_test`
- `docs/TEAM_CODE_FLOW_KR.md`에 전체 흐름과 파일별 책임·터미널 시험 방법을 기록했습니다.
- `docs/TEAM_CONTRACT_V1.md`와 ROS `.srv/.msg/.action` 주석을 인터페이스 검토 기준으로 사용해 주세요.

**초기 시스템 그림에서 추가·변경된 부분:** `/art/control_job` Service(PAUSE/RESUME/CANCEL)를 신규 추가했습니다. 초기 `/art/execute_job`·`/art/prepare_artwork`·`/art/draw_artwork`·`/art/draw_calligraphy`와 달리 현재는 JobManager→Controller의 `/art/execute_drawing` Action 하나를 제안했습니다. 기존 사진→DrawingPlan 자동 생성과 실물 Controller는 아직 연결 전입니다.

장태원: `drawing_plan.json` 형식·좌표·작업 경로를 확인해 주세요.
류민선: `ExecuteDrawing.action` Feedback/Result와 실제 정지·펜 이격 확인 방법을 검토해 주세요.
배준영: `ControlJob.srv`와 `JobStatus.msg`를 기준으로 요청 수락/실제 정지 상태를 구분해 주세요.

이 파일들은 팀 수락 전 v1 제안안이므로, 호환 불가능한 필드나 안전 문제가 있으면 변경 사유를 회신해 주세요.
