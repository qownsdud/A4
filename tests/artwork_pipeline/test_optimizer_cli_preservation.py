"""보조 CLI의 기본 실행이 사진의 획을 임의로 제거하지 않는지 검증합니다."""
import json
import sys
from art_artwork_pipeline.path_planner.drawing_plan import build_plan, validate_plan
from art_artwork_pipeline.path_planner import optimize_existing

def test_cli_preserves_more_than_48_separate_strokes(tmp_path, monkeypatch):
    paths = [{'points': [[x*10, y*10], [x*10+2, y*10+2]]}
             for x in range(10) for y in range(6)]
    plan = build_plan(paths, 100, 60, job_id='FULL')
    source, output = tmp_path/'input.json', tmp_path/'output.json'
    source.write_text(json.dumps(plan))
    monkeypatch.setattr(sys, 'argv', ['optimize', '--input', str(source), '--output', str(output), '--backend', 'opencv'])
    optimize_existing.main()
    actual = json.loads(output.read_text())
    validate_plan(actual)
    assert len(actual['strokes']) == len(plan['strokes']) == 60
    assert json.loads(source.read_text()) == plan
