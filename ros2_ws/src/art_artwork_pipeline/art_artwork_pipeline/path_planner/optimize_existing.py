"""Optimize an existing DrawingPlan JSON without overwriting the source."""
import argparse
import json
from pathlib import Path
from .path_optimizer import optimize_plan
from .drawing_plan import validate_plan, write_job_plan

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--strokes',type=int,default=None,help='명시한 경우에만 획 수를 줄입니다. 기본값은 전체 획 보존입니다.')
    p.add_argument('--backend',choices=['auto','opencv','vpype'],default='opencv')
    p.add_argument('--plan-root',type=Path,default=None,help='publish immutable per-job plan')
    args=p.parse_args()
    if args.input.resolve()==args.output.resolve():p.error('input and output must differ')
    source=json.loads(args.input.read_text(encoding='utf-8'))
    validate_plan(source)
    result=optimize_plan(source,max_strokes=args.strokes,backend=args.backend)
    validate_plan(result)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(result,f,ensure_ascii=False,indent=2)
    print(f"Saved {len(result['strokes'])} strokes to {args.output}")
    if args.plan_root is not None:
        print('Published', write_job_plan(result, args.plan_root))
if __name__=='__main__':main()
