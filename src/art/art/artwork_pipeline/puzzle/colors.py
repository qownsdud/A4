"""4×4 퍼즐의 논리 펜 배정. 최적화와 분리합니다."""
import random
PENS = ('PEN_1', 'PEN_2', 'PEN_3')
def balanced_cells(seed=42, pen_ids=PENS):
    if tuple(pen_ids) != PENS:
        raise ValueError('PEN_1, PEN_2, PEN_3가 필요합니다.')
    cells = [pen_ids[0]] * 6 + [pen_ids[1]] * 5 + [pen_ids[2]] * 5
    random.Random(seed).shuffle(cells)
    return cells
