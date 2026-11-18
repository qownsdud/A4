"""정상 좌표는 RAM에, 예외의 복귀 정보만 SQLite 트랜잭션에 저장합니다."""

from collections import deque
import copy
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


def recovery_db_path(root=None):
    if os.environ.get('ART_RECOVERY_DB'):
        return Path(os.environ['ART_RECOVERY_DB']).expanduser()
    if root is None:
        from .pipeline_runner import job_root
        root = job_root()
    return Path(root)/'.recovery'/'recovery.sqlite3'


class CheckpointStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else recovery_db_path()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=2., isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=2000')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('''CREATE TABLE IF NOT EXISTS recovery_checkpoints (
            checkpoint_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL UNIQUE,
            job_id TEXT NOT NULL, plan_path TEXT NOT NULL, plan_sha256 TEXT NOT NULL,
            created_at REAL NOT NULL, cause TEXT NOT NULL, state TEXT NOT NULL,
            stroke_id INTEGER, point_index INTEGER, payload_json TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS recovery_job_idx ON recovery_checkpoints(job_id,created_at)')
        return db

    def save(self, *, incident_id, job_id, plan_path, plan_sha256, cause, payload):
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        cursor = payload.get('waypoint') or {}
        checkpoint_id = uuid.uuid4().hex
        db = self._connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT checkpoint_id FROM recovery_checkpoints WHERE incident_id=?',(incident_id,)).fetchone()
            if old:
                db.execute('COMMIT')
                return old[0]
            db.execute("UPDATE recovery_checkpoints SET state='superseded' WHERE job_id=? AND state IN ('pending','resuming')",(job_id,))
            db.execute('INSERT INTO recovery_checkpoints VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (checkpoint_id,incident_id,job_id,str(plan_path),plan_sha256,time.time(),cause,'pending',
                        cursor.get('stroke_id'),cursor.get('point_index'),raw))
            db.execute('COMMIT')
            return checkpoint_id
        except Exception:
            if db.in_transaction: db.execute('ROLLBACK')
            raise
        finally: db.close()

    def latest(self, job_id=None, checkpoint_id=None):
        # 정상 조회에서는 DB 파일이 없으면 만들지 않습니다.
        if not self.path.is_file():return None
        db = sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2.)
        db.row_factory = sqlite3.Row
        try:
            query="SELECT * FROM recovery_checkpoints WHERE state IN ('pending','resuming')"
            args=[]
            if job_id is not None:query+=' AND job_id=?';args.append(job_id)
            if checkpoint_id is not None:query+=' AND checkpoint_id=?';args.append(checkpoint_id)
            row=db.execute(query+' ORDER BY created_at DESC,rowid DESC LIMIT 1',args).fetchone()
            if row is None:return None
            result=dict(row);result['payload']=json.loads(result.pop('payload_json'))
            return result
        finally:db.close()

    def update_runtime(self, checkpoint_id, runtime):
        """홈 도달 같은 저빈도 복구 전이만 갱신합니다. 주행 샘플은 쓰지 않습니다."""
        db=self._connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload_json FROM recovery_checkpoints WHERE checkpoint_id=?',(checkpoint_id,)).fetchone()
            if row is None:raise ValueError('갱신할 중단점이 없습니다.')
            payload=json.loads(row[0]);payload['runtime']=copy.deepcopy(runtime)
            db.execute('UPDATE recovery_checkpoints SET payload_json=? WHERE checkpoint_id=?',
                (json.dumps(payload,ensure_ascii=False,allow_nan=False),checkpoint_id))
            db.execute('COMMIT')
        except Exception:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        finally:db.close()

    def mark(self, job_id, state):
        if state not in ('resuming','resolved','abandoned'):raise ValueError('잘못된 복구 상태입니다.')
        if not self.path.is_file():return
        db=self._connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE recovery_checkpoints SET state=? WHERE job_id=? AND state IN ('pending','resuming')",(state,job_id))
            db.execute('COMMIT')
        finally:db.close()


class RecoveryJournal:
    def __init__(self, job_id, plan_path, plan_sha256, *, store=None, maxlen=100):
        self.job_id=job_id;self.plan_path=str(plan_path);self.plan_sha256=plan_sha256
        self.store=store or CheckpointStore()
        self.samples=deque(maxlen=maxlen)
        self.runtime={};self.cursor=None;self.checkpoint_id=None;self.incident_cause=None

    def sample(self, *, target_pose, actual_pose, force, waypoint, completed_strokes, completed_length_mm, runtime):
        self.cursor=copy.deepcopy(waypoint)
        self.runtime=copy.deepcopy(runtime)
        self.samples.append(dict(timestamp=time.time(),monotonic=time.monotonic(),
            target_pose=list(target_pose),actual_pose=list(actual_pose),force=list(force),
            waypoint=copy.deepcopy(waypoint),completed_strokes=completed_strokes,
            completed_length_mm=completed_length_mm,runtime=copy.deepcopy(runtime)))

    def interrupt(self, cause, actual_pose, *, stop_confirmed, force=None):
        if self.checkpoint_id and self.incident_cause==cause:return self.checkpoint_id
        self.incident_cause=cause
        sample=next((s for s in reversed(self.samples) if s['runtime'].get('held_pen_id')==self.runtime.get('held_pen_id')),None)
        payload=dict(version=1,waypoint=sample['waypoint'] if sample else None,
                     target_pose=sample['waypoint']['return_pose'] if sample else None,
                     inflight_target_pose=sample['target_pose'] if sample else None,
                     last_safe_actual_pose=sample['actual_pose'] if sample else None,
                     actual_pose_at_fault=actual_pose,force_at_fault=force,
                     stop_confirmed=bool(stop_confirmed),runtime=copy.deepcopy(self.runtime),
                     completed_strokes=sample['completed_strokes'] if sample else 0,
                     completed_length_mm=sample['waypoint']['base_length_mm'] if sample else 0.,
                     sample_timestamp=sample['timestamp'] if sample else None,
                     resumable=bool(sample and self.runtime.get('phase') in ('drawing','stroke_lift')))
        self.checkpoint_id=self.store.save(incident_id=uuid.uuid4().hex,job_id=self.job_id,
            plan_path=self.plan_path,plan_sha256=self.plan_sha256,cause=cause,payload=payload)
        return self.checkpoint_id

    def restore(self, checkpoint):
        data=checkpoint['payload'];self.runtime=copy.deepcopy(data['runtime'])
        if data.get('waypoint'):
            self.sample(target_pose=data['inflight_target_pose'],actual_pose=data['last_safe_actual_pose'],
                force=data.get('force_at_fault') or [0.]*6,waypoint=data['waypoint'],
                completed_strokes=data['completed_strokes'],completed_length_mm=data['completed_length_mm'],runtime=data['runtime'])
        self.checkpoint_id=checkpoint['checkpoint_id'];self.incident_cause=checkpoint['cause']

    def resumed(self):
        self.store.mark(self.job_id,'resuming');self.checkpoint_id=None
