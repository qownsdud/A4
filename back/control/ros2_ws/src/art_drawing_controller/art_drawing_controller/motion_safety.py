"""실물 동작 허용 이전의 제한 검사. 현재 어댑터는 항상 거절합니다."""
import math
def validate_pose(pose, limits):
    if len(pose)!=3 or len(limits)!=3:
        raise ValueError('XYZ 제한이 필요합니다.')
    for value,(low,high) in zip(pose,limits):
        if not all(math.isfinite(v) for v in (value,low,high)) or not low <= value <= high:
            raise ValueError('허용 모션 범위를 벗어납니다.')
    return True
