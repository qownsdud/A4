"""종이 mm → 로봇 기준 XYZ. 픽셀 변환과 독립된 순수 좌표 연산입니다."""
import math
def paper_to_robot(point, *, origin, x_axis, y_axis):
    if any(len(v)!=3 for v in (origin,x_axis,y_axis)) or len(point)!=2:
        raise ValueError('좌표 차원이 잘못되었습니다.')
    if not all(math.isfinite(v) for vector in (origin,x_axis,y_axis,point) for v in vector):
        raise ValueError('유한 좌표가 필요합니다.')
    if not (0 <= point[0] <= 210 and 0 <= point[1] <= 297):
        raise ValueError('종이 범위를 벗어납니다.')
    if any(abs(sum(v*v for v in axis)-1)>1e-6 for axis in (x_axis,y_axis)) or abs(sum(a*b for a,b in zip(x_axis,y_axis)))>1e-6:
        raise ValueError('서로 수직인 단위 축이 필요합니다.')
    return tuple(origin[i]+point[0]*x_axis[i]+point[1]*y_axis[i] for i in range(3))
