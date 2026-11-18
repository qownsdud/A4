# [파일 역할] 샘플 DrawingPlan JSON 생성기
# [동작] JobManager가 읽을 수 있는 작업별 drawing_plan.json을 생성합니다.
# [주의] 실제 사진을 벡터 경로로 변환하는 기능은 없습니다.
# 팀원은 docs/TEAM_CODE_FLOW_KR.md를 먼저 읽으면 파일 간 연결 흐름을 이해할 수 있습니다.

"""Create a per-job simulation-only DrawingPlan. No robot actions."""
import argparse
import json
from pathlib import Path


# [핵심 기능] 실행 진입점: 환경 변수, ROS 초기화, spin 및 종료 처리
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('job_id', help='e.g. JOB_SIM_002')
    parser.add_argument('--strokes', type=int, default=200)
    args = parser.parse_args()
    if not args.job_id.replace('_', '').replace('-', '').isalnum() or not 1 <= args.strokes <= 2000:
        parser.error('job_id must be alphanumeric with _/- and strokes 1..2000')
    root = Path(__file__).resolve().parent
    out_dir = root / args.job_id
    out_dir.mkdir(exist_ok=True)
    target = out_dir / 'drawing_plan.json'
    if target.exists():
        parser.error(f'File exists, refusing to overwrite immutable plan: {target}')
    strokes = []
    for idx in range(1, args.strokes + 1):
        x, y = 10 + (idx * 3 % 180), 20 + (idx * 7 % 250)
        strokes.append({'stroke_id': idx, 'pen_id': f'PEN_{1 + (idx - 1) // 50 % 3}',
                        'points_mm': [[x, y], [min(205, x + 4), min(292, y + 4)]]})
    target.write_text(json.dumps({'schema_version': '0.1', 'job_id': args.job_id,
                   'paper_mm': {'width': 210, 'height': 297}, 'strokes': strokes},
                   ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main()
