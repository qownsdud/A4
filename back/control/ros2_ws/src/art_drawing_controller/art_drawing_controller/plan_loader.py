"""Controller 신뢰 경계에서 JobManager와 같은 계약 및 SHA를 재검사합니다."""
import hashlib
import json
from art_job_manager.plan import load_plan
def load_execution_plan(job_id, path, sha256, *, root):
    summary = load_plan(job_id,path,plan_root=root)
    data = open(summary.path,'rb').read()
    if summary.sha256 != sha256 or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError('실행 계획 SHA-256이 일치하지 않습니다.')
    return json.loads(data)
