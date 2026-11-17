"""영문 대소문자와 공백을 종이 mm 경로로 변환합니다. 한글은 거절합니다."""
import math
from .cursive_font import CURSIVE_GLYPHS, _interpolate_stroke
def generate_strokes(text, *, origin=(15., 270.), height_mm=8., pen_id='PEN_1'):
    if not isinstance(text, str) or len(text) > 120 or any(c not in CURSIVE_GLYPHS for c in text):
        raise ValueError('영문 A-Z, a-z와 공백만 지원합니다.')
    if not math.isfinite(height_mm) or not 0 < height_mm <= 30 or pen_id not in ('PEN_1','PEN_2','PEN_3'):
        raise ValueError('잘못된 문자 크기 또는 펜입니다.')
    x, baseline = origin
    strokes = []
    for ch in text:
        advance, glyph = CURSIVE_GLYPHS[ch]
        for control in glyph:
            points = [[round(x+a*height_mm,3),round(baseline-b*height_mm,3)] for a,b in _interpolate_stroke(control)]
            if any(not (0 <= a <= 210 and 0 <= b <= 297) for a,b in points):
                raise ValueError('문구가 A4 범위를 벗어납니다.')
            strokes.append(dict(pen_id=pen_id,layer='calligraphy',points_mm=points))
        x += advance * height_mm
    return strokes
