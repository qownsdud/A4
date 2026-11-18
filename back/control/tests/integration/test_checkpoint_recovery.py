# [파일 역할] KioskBridge 통합 회귀 테스트
# [동작] HTTP→ROS 계약, 상태 캐시, 오류 처리, 정지·복구 시나리오를 자동 검증합니다.
# [주의] 테스트를 실행한다고 실제 로봇이 움직이지 않습니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""SQLite mock contract tests; not a verification of real JobManager repository."""

from mocks.checkpoint_stub import CheckpointStub


# [핵심 기능] pytest: only lift confirmed stroke is complete 조건을 검증
def test_only_lift_confirmed_stroke_is_complete(tmp_path):
    db = tmp_path / "job.db"
    first = CheckpointStub(db)
    first.begin_stroke("J1", 1, "PEN_RED")
    assert first.complete_stroke("J1", 1, pen_lift_confirmed=False) is False
    assert first.get("J1") == (0, 1, "PEN_RED")
    assert first.complete_stroke("J1", 1, pen_lift_confirmed=True) is True
    first.begin_stroke("J1", 2, "PEN_RED")
    assert first.get("J1") == (1, 2, "PEN_RED")
    first.close()

    restarted = CheckpointStub(db)
    assert restarted.get("J1") == (1, 2, "PEN_RED")
    # TEAM_SYNC(JobManager/Robot): a real operator must inspect stroke 2;
    # DO NOT auto-redraw it after restarting the application.
    restarted.close()
