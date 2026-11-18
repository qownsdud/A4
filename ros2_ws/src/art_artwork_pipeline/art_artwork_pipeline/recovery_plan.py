"""중단점은 실측 좌표가 아니라 불변 계획의 인덱스와 다시 대조합니다."""

import hashlib
import math
from pathlib import Path


def resource_hashes(paths):
    return {Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}


def verify_checkpoint(checkpoint, ordered_strokes, *, plan_sha256, resources, tool_name, tcp_name, z_offsets):
    if checkpoint['plan_sha256'] != plan_sha256:raise ValueError('중단점의 DrawingPlan SHA-256이 다릅니다.')
    data=checkpoint['payload'];runtime=data['runtime'];waypoint=data.get('waypoint')
    if not data.get('resumable') or not waypoint:raise ValueError('복구 가능한 드로잉 웨이포인트가 없습니다.')
    if runtime.get('resource_hashes')!=resources or runtime.get('tool_name')!=tool_name or runtime.get('tcp_name')!=tcp_name:
        raise ValueError('보정 파일 또는 Tool/TCP가 중단 당시와 다릅니다.')
    record_index=next((i for i,r in enumerate(ordered_strokes) if r['stroke_id']==waypoint['stroke_id']),None)
    if record_index is None:raise ValueError('중단점의 획을 계획에서 찾을 수 없습니다.')
    record=ordered_strokes[record_index];index=waypoint['point_index'];points=record['points_robot']
    if type(index) is not int or not 1<=index<len(points):raise ValueError('중단점의 점 인덱스가 잘못됐습니다.')
    if waypoint['pen_id']!=record['pen_id'] or runtime.get('held_pen_id')!=record['pen_id']:
        raise ValueError('중단점의 펜과 계획의 펜이 다릅니다.')
    contact=runtime['contact_pose'];a,b=runtime['slope_a'],runtime['slope_b']
    if len(contact)!=6 or not all(type(v) in (int,float) and math.isfinite(v) for v in [*contact,a,b]):
        raise ValueError('중단점의 기준면 수치가 잘못됐습니다.')
    pen_index=int(record['pen_id'].split('_')[1])-1
    def pose(point):
        x,y=point
        return [x,y,contact[2]+a*(x-contact[0])+b*(y-contact[1])+z_offsets[pen_index],*contact[3:]]
    expected=pose(points[index-1]);inflight=pose(points[index])
    for actual,target in ((data['target_pose'],expected),(data['inflight_target_pose'],inflight)):
        if len(actual)!=6 or any(not math.isfinite(v) or abs(v-t)>1e-6 for v,t in zip(actual,target)):
            raise ValueError('저장된 복귀점이 원래 계획과 다릅니다. 자동 복귀하지 않습니다.')
    base=sum(sum(math.dist(a,b) for a,b in zip(r['points_robot'],r['points_robot'][1:])) for r in ordered_strokes[:record_index])
    base+=sum(math.dist(a,b) for a,b in zip(points[:index],points[1:index]))
    if abs(data['completed_length_mm']-base)>1e-5 or data['completed_strokes']!=record_index:
        raise ValueError('중단점의 완료 길이 또는 획 수가 계획과 맞지 않습니다.')
    return record_index,index


def verify_cleanup_context(checkpoint, *, resources, tool_name, tcp_name, pen_poses, stick_pose):
    runtime=checkpoint['payload']['runtime']
    if runtime.get('resource_hashes')!=resources or runtime.get('tool_name')!=tool_name or runtime.get('tcp_name')!=tcp_name:
        raise ValueError('이전 펜 정리의 보정 또는 Tool/TCP가 변경됐습니다.')
    held=runtime.get('held_item')
    if not held:raise ValueError('정리할 파지 물체의 기록이 없습니다.')
    if held['kind']=='stick':expected=stick_pose
    elif held['kind']=='pen' and runtime.get('held_pen_id') in ('PEN_1','PEN_2','PEN_3'):
        expected=pen_poses[int(runtime['held_pen_id'].split('_')[1])-1]
    else:raise ValueError('파지 물체 기록을 확인할 수 없습니다.')
    if len(held['pose'])!=6 or any(not math.isfinite(v) or abs(v-e)>1e-6 for v,e in zip(held['pose'],expected)):
        raise ValueError('이전 파지 물체의 슬롯 좌표가 달라졌습니다.')
    return list(expected),held['name']
