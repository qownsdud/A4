"""중간 획 보존 모드와 재시작·계획 변조의 안전 경계를 검증합니다."""
from pathlib import Path
from art_job_manager.production_engine import ProductionEngine
from art_artwork_pipeline.path_planner.drawing_plan import build_plan,write_job_plan

def started(tmp_path):
    plan=build_plan([{'points':[[0,0],[10,10]]}],20,20,job_id='LIVE')
    path=write_job_plan(plan,tmp_path)
    engine=ProductionEngine(tmp_path/'jobs.db',plan_root=tmp_path)
    assert engine.create_job('LIVE',str(path)).accepted
    assert engine.prepare_dispatch('LIVE')
    assert engine.on_controller_started('LIVE',live_execution=True)
    assert engine.on_stroke_started('LIVE',1,plan['strokes'][0]['pen_id'])
    return engine,path

def test_live_resume_keeps_partial_stroke_and_does_not_queue_new_goal(tmp_path):
    engine,_=started(tmp_path)
    try:
        assert engine.control_job('LIVE','PAUSE','p').state=='PAUSING'
        assert engine.on_live_control('LIVE','PAUSE')
        paused=engine.status('LIVE')
        assert paused['uncertain_stroke']==1 and paused['completed_strokes']==0
        assert paused['error_code']==''
        assert engine.control_job('LIVE','RESUME','r').state=='RESUMING'
        assert engine.prepare_dispatch('LIVE') is None
        assert engine.on_live_control('LIVE','RESUME')
        assert engine.status('LIVE')['uncertain_stroke']==1
        assert engine.on_stroke_completed('LIVE',1,pen_up_confirmed=True)
    finally:engine.close()

def test_live_paused_cancel_is_not_immediate_success(tmp_path):
    engine,_=started(tmp_path)
    try:
        engine.control_job('LIVE','PAUSE','p');engine.on_live_control('LIVE','PAUSE')
        assert engine.control_job('LIVE','CANCEL','c').state=='STOPPING'
        assert engine.on_action_result('LIVE',ros_status=5,success=False,final_state='INTERRUPTED_SAFE',
                                       completed_strokes=0,pen_up_confirmed=True)
        assert engine.status('LIVE')['state']=='STOPPED'
    finally:engine.close()

def test_live_pause_restart_never_resumes_lost_controller_context(tmp_path):
    engine,_=started(tmp_path)
    engine.control_job('LIVE','PAUSE','p');engine.on_live_control('LIVE','PAUSE');engine.close()
    engine=ProductionEngine(tmp_path/'jobs.db',plan_root=tmp_path)
    try:
        assert engine.status('LIVE')['state']=='RECOVERY_REQUIRED'
        assert not engine.control_job('LIVE','RESUME','r').accepted
    finally:engine.close()

def test_live_resume_refuses_changed_plan(tmp_path):
    engine,path=started(tmp_path)
    try:
        engine.control_job('LIVE','PAUSE','p');engine.on_live_control('LIVE','PAUSE')
        path.write_text(path.read_text()+' ')
        assert engine.control_job('LIVE','RESUME','r').error_code=='PLAN_CHANGED'
        assert engine.status('LIVE')['state']=='PAUSED'
    finally:engine.close()

def test_existing_database_migration_preserves_history_and_partial_stroke(tmp_path):
    import sqlite3
    engine,_=started(tmp_path)
    engine.close()
    with sqlite3.connect(tmp_path/'jobs.db') as con:
        con.execute('ALTER TABLE jobs DROP COLUMN live_execution')
    engine=ProductionEngine(tmp_path/'jobs.db',plan_root=tmp_path)
    try:
        row=engine.status('LIVE')
        assert row['live_execution']==0
        assert row['uncertain_stroke']==1 and row['completed_strokes']==0
        assert row['state']=='RECOVERY_REQUIRED'
    finally:engine.close()

def test_live_action_ending_during_pause_cannot_be_resumed_as_retained_motion(tmp_path):
    engine,_=started(tmp_path)
    try:
        engine.control_job('LIVE','PAUSE','p')
        assert not engine.on_action_result('LIVE',ros_status=5,success=False,
            final_state='INTERRUPTED_SAFE',completed_strokes=0,pen_up_confirmed=True)
        assert engine.status('LIVE')['state']=='RECOVERY_REQUIRED'
        assert not engine.control_job('LIVE','RESUME','r').accepted
    finally:engine.close()
