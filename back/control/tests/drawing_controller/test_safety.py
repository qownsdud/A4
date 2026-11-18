import pytest
from art_drawing_controller.doosan_adapter import DoosanAdapter
from art_drawing_controller.paper_transform import paper_to_robot
from art_drawing_controller.motion_safety import validate_pose
from art_drawing_controller.plan_loader import load_execution_plan
from art_artwork_pipeline.path_planner.drawing_plan import build_plan,write_job_plan
from art_job_manager.plan import load_plan

def test_unvalidated_hardware_never_moves():
    with pytest.raises(RuntimeError):
        DoosanAdapter().move([0,0,0])

def test_paper_transform_and_limits():
    assert paper_to_robot((10,20),origin=(100,200,300),x_axis=(1,0,0),y_axis=(0,-1,0))==(110,180,300)
    with pytest.raises(ValueError):
        paper_to_robot((211,20),origin=(0,0,0),x_axis=(1,0,0),y_axis=(0,1,0))
    with pytest.raises(ValueError):
        validate_pose([0,0,1000],[(-100,100)]*3)

def test_controller_revalidates_sha(tmp_path):
    plan=build_plan([{'points':[[0,0],[10,10]]}],20,20,job_id='J1')
    path=write_job_plan(plan,tmp_path)
    summary=load_plan('J1',str(path),plan_root=tmp_path)
    assert load_execution_plan('J1',str(path),summary.sha256,root=tmp_path)['job_id']=='J1'
    with pytest.raises(ValueError):
        load_execution_plan('J1',str(path),'0'*64,root=tmp_path)
