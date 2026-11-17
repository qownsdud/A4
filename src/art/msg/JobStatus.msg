# [역할] JobManager → Bridge : 작업의 관측된 상태/진행률을 Topic으로 게시
# Bridge는 이 메시지를 캐시하고 GET /bridge/jobs/{job_id}에 사용합니다.
# 요청 수락과 실제 상태는 별개입니다. 이 메시지만 보고 진행률 UI를 갱신하세요.
string job_id             # 작업 ID
string state              # QUEUED / DISPATCHING / DRAWING / PAUSING / PAUSED / STOPPING / STOPPED / COMPLETED / RECOVERY_REQUIRED 등
uint32 completed_strokes  # 펜 이격까지 확인된 연속 완료 획 수
uint32 total_strokes      # DrawingPlan 내 전체 획 수
string current_pen        # 현재 펜 이름 (예: PEN_1)
string error_code         # 오류 코드, 정상일 때는 빈 문자열
string message            # 상태 설명
