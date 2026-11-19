"""용지 규격·사진 배치·문구 영역의 단일 기준. 로봇 좌표와는 무관합니다."""

from PIL import Image

LANDSCAPE = "a4_landscape_margin"


def layout(paper="a4", text=False):
    if paper == LANDSCAPE:
        return dict(
            size=(297.0, 210.0),
            margin=20.0,
            artwork=(20.0, 20.0, 257.0, 140.0 if text else 170.0),
            text_origin=(50.0, 180.0),
            text_bounds=(50.0, 165.0, 247.0, 190.0),
        )
    if paper == "a4":
        return dict(
            size=(210.0, 297.0),
            margin=15.0,
            artwork=(15.0, 15.0, 180.0, 225.0 if text else 267.0),
            text_origin=(45.0, 270.0),
            text_bounds=(45.0, 250.0, 165.0, 282.0),
        )
    raise ValueError("계획은 A4 가로 또는 세로만 지원합니다.")


def fit_landscape_preview(image):
    """참고 Kiosk의 3 px/mm·사방 20mm 배치. 재배치는 이 함수에서 한 번만 합니다."""
    rgb = image.convert("RGB")
    scale = min(771 / rgb.width, 510 / rgb.height)
    size = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
    rgb = rgb.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (891, 630), "white")
    canvas.paste(rgb, (60 + (771 - size[0]) // 2, 60 + (510 - size[1]) // 2))
    return canvas
