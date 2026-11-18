"""슬라이더 0~100을 CV·DL·얼굴 Canny 설정에 공통으로 적용합니다."""

import re


def detail_parameters(value):
    aliases = {"low": 0, "medium": 50, "high": 100}
    if value in aliases:
        level = aliases[value]
    elif isinstance(value, str) and re.fullmatch(r"(?:100|[0-9]{1,2})", value):
        level = int(value)
    else:
        raise ValueError("디테일은 0~100 또는 low/medium/high여야 합니다.")
    return dict(
        level=level,
        smooth=round(2 * (1 - level / 100)),
        threshold=round(200 + level * 0.2),
        area=round(5 - level * 0.03),
        canny_low=round(90 - level * 0.7),
        canny_high=round(210 - level * 1.1),
    )
