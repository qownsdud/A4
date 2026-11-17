"""순서 검사 후 어댑터 준비 상태를 요구합니다. 성공을 모사하지 않습니다."""
def execution_strokes(plan, start_stroke_id=1):
    strokes = plan['strokes']
    if type(start_stroke_id) is not int or not 1 <= start_stroke_id <= len(strokes):
        raise ValueError('재개 획 번호가 잘못되었습니다.')
    if [s['stroke_id'] for s in strokes] != list(range(1,len(strokes)+1)):
        raise ValueError('획 순서가 잘못되었습니다.')
    return strokes[start_stroke_id-1:]

def execute(plan, adapter, start_stroke_id=1):
    strokes = execution_strokes(plan,start_stroke_id)
    adapter.require_ready()
    raise RuntimeError('실물 획 실행은 검증 전입니다.')
