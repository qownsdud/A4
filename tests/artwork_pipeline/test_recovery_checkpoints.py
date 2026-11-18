"""실측 충돌 좌표와 계획 복귀점의 분리·영속 보존·이어 그리기를 검증합니다."""

import json
import sqlite3
from pathlib import Path
import pytest
from art_artwork_pipeline.recovery_store import CheckpointStore,RecoveryJournal
from art_artwork_pipeline.recovery_plan import verify_checkpoint


def journal(tmp_path):
    store=CheckpointStore(tmp_path/'recovery.sqlite3')
    j=RecoveryJournal('JOB',tmp_path/'drawing_plan.json','HASH',store=store,maxlen=100)
    j.runtime=dict(held_pen_id='PEN_2',phase='drawing',contact_pose=[0.,0.,0.,0.,0.,0.],
                   slope_a=0.,slope_b=0.,resource_hashes={'plane':'same'},tool_name='Tool_Weight',tcp_name='GripperDA_v1')
    return j


def test_ring_has_no_database_writes_during_normal_drawing_and_incident_is_once(tmp_path):
    j=journal(tmp_path)
    for i in range(250):
        waypoint=dict(stroke_id=2,point_index=1,return_pose=[10.,10.,0.,0.,0.,0.],base_length_mm=10.,pen_id='PEN_2')
        j.sample(target_pose=[100.,10.,0.,0.,0.,0.],actual_pose=[40.,10.,0.,0.,0.,0.],force=[0.]*6,
                 waypoint=waypoint,completed_strokes=1,completed_length_mm=40.,runtime=j.runtime)
    assert len(j.samples)==100 and not j.store.path.exists()
    cid=j.interrupt('EXTERNAL_FORCE',[47.,17.,0.,0.,0.,0.],stop_confirmed=True,force=[20.,0.,0.,0.,0.,0.])
    assert j.interrupt('EXTERNAL_FORCE',[47.,17.,0.,0.,0.,0.],stop_confirmed=True)==cid
    row=CheckpointStore(j.store.path).latest(job_id='JOB')
    assert row['payload']['target_pose'][:2]==[10.,10.]
    assert row['payload']['inflight_target_pose'][:2]==[100.,10.]
    assert row['payload']['actual_pose_at_fault'][:2]==[47.,17.]
    with sqlite3.connect(j.store.path) as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
        assert db.execute('SELECT count(*) FROM recovery_checkpoints').fetchone()[0]==1
    j.store.mark('JOB','resuming');assert j.store.latest()['state']=='resuming'
    j.store.mark('JOB','abandoned');assert j.store.latest() is None
    with sqlite3.connect(j.store.path) as db:assert db.execute('SELECT count(*) FROM recovery_checkpoints').fetchone()[0]==1


def test_recovery_revalidates_waypoint_against_original_plan_and_hash(tmp_path):
    j=journal(tmp_path)
    waypoint=dict(stroke_id=2,point_index=1,return_pose=[10.,10.,0.,0.,0.,0.],base_length_mm=10.,pen_id='PEN_2')
    j.sample(target_pose=[100.,10.,0.,0.,0.,0.],actual_pose=[40.,10.,0.,0.,0.,0.],force=[0.]*6,
             waypoint=waypoint,completed_strokes=1,completed_length_mm=40.,runtime=j.runtime)
    j.interrupt('STOP',[40.,10.,0.,0.,0.,0.],stop_confirmed=True)
    row=j.store.latest()
    records=[dict(stroke_id=1,pen_id='PEN_1',points_robot=[[0.,0.],[10.,0.]]),dict(stroke_id=2,pen_id='PEN_2',points_robot=[[10.,10.],[100.,10.]])]
    args=dict(plan_sha256='HASH',resources={'plane':'same'},tool_name='Tool_Weight',tcp_name='GripperDA_v1',z_offsets=[0.]*3)
    assert verify_checkpoint(row,records,**args)==(1,1)
    with pytest.raises(ValueError):verify_checkpoint(row,records,**dict(args,plan_sha256='CHANGED'))
    with pytest.raises(ValueError):verify_checkpoint(row,records,**dict(args,resources={}))
    row['payload']['target_pose']=[47.,17.,0.,0.,0.,0.]
    with pytest.raises(ValueError,match='원래 계획'):verify_checkpoint(row,records,**args)


def test_checkpoint_recovery_moves_to_safe_waypoint_not_bumped_pose(tmp_path):
    from art_artwork_pipeline.live_control import LiveControl
    from robot_worker_fixture import FakeApi
    j=journal(tmp_path)
    waypoint=dict(stroke_id=2,point_index=1,return_pose=[10.,10.,0.,0.,0.,0.],base_length_mm=10.,pen_id='PEN_2')
    j.sample(target_pose=[100.,10.,0.,0.,0.,0.],actual_pose=[40.,10.,0.,0.,0.,0.],force=[0.]*6,
             waypoint=waypoint,completed_strokes=1,completed_length_mm=40.,runtime=j.runtime)
    j.interrupt('FORCE',[47.,17.,0.,0.,0.,0.],stop_confirmed=True)
    api=FakeApi();api.current=[47.,17.,0.,0.,0.,0.];api.target=api.current[:]
    c=LiveControl('JOB',100.,2,dict(protection_mode='controller',motion_timeout=2.,position_tolerance=.1,joint_tolerance=.1),emit=lambda event:None)
    c.bind(api,api.home,lambda p:50.);c.attach_journal(j);c.recovery_move(j.store.latest())
    assert api.commands[-1][0]==[10.,10.,0.,0.,0.,0.]
    assert all(target[:2]!=[47.,17.] or target[2]>0 for target,joint in api.commands)
    assert c.done==10. and c.completed==1 and c.run_id==1


def test_restart_from_disk_restores_pause_home_and_planned_waypoint(tmp_path):
    from art_artwork_pipeline.live_control import LiveControl
    from robot_worker_fixture import FakeApi
    j=journal(tmp_path)
    waypoint=dict(stroke_id=2,point_index=1,return_pose=[10.,10.,0.,0.,0.,0.],base_length_mm=10.,pen_id='PEN_2')
    j.sample(target_pose=[100.,10.,0.,0.,0.,0.],actual_pose=[40.,10.,0.,0.,0.,0.],force=[0.]*6,
             waypoint=waypoint,completed_strokes=1,completed_length_mm=40.,runtime=j.runtime)
    cid=j.interrupt('PAUSE',[40.,10.,0.,0.,0.,0.],stop_confirmed=True)
    j.runtime['pause_home']=dict(home=[0.,0.,100.,0.,0.,0.],return_joints=[40.,10.,50.,0.,0.,0.],lifted=[40.,10.,50.,0.,0.,0.])
    j.store.update_runtime(cid,j.runtime)
    # 원래 객체를 버리고 디스크에서 새 세션으로 읽습니다.
    store_path=j.store.path;del j
    checkpoint=CheckpointStore(store_path).latest(job_id='JOB')
    restored=RecoveryJournal('JOB',tmp_path/'drawing_plan.json','HASH',store=CheckpointStore(store_path))
    restored.restore(checkpoint)
    api=FakeApi();api.current=api.home[:];api.target=api.current[:]
    c=LiveControl('JOB',100.,2,dict(protection_mode='controller',motion_timeout=2.,position_tolerance=.1,joint_tolerance=.1),emit=lambda e:None)
    c.bind(api,api.home,lambda p:50.);c.attach_journal(restored)
    c.recovery_move(checkpoint)
    assert api.commands[0]==([40.,10.,50.,0.,0.,0.],True)
    assert api.commands[-1][0]==[10.,10.,0.,0.,0.,0.]
    assert c.completed==1 and c.done==10. and c.run_id==1
    assert 'pause_home' not in c.runtime


def test_sqlite_failure_does_not_expose_successful_checkpoint(tmp_path):
    j=journal(tmp_path)
    j.store.path.write_bytes(b'corrupted database')
    with pytest.raises(sqlite3.DatabaseError):j.interrupt('STOP',[0.]*6,stop_confirmed=True)
    assert j.checkpoint_id is None
