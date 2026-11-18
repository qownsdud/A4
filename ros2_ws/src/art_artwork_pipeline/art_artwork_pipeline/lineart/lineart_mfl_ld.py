"""참고 코드의 혼합 선화: MediaPipe 얼굴 영역은 Canny, 비얼굴 영역은 LineartDetector."""

from dataclasses import dataclass, field
from pathlib import Path
import os

import cv2
import numpy as np
from PIL import Image

from .lineart_dl import LineartConverterDL, LineartDLConfig
from .utils import ImageInput, load_pil_rgb, pad_to_paper_ratio

DEFAULT_FACE_MODEL_PATH = Path(
    os.environ.get(
        "ART_FACE_MODEL_PATH",
        str(Path.home() / ".cache/a4/models/face_landmarker.task"),
    )
).expanduser()
DEFAULT_FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)


def _ensure_face_model(model_path: Path, model_url: str) -> Path:
    if model_path.is_file():
        return model_path
    raise FileNotFoundError(
        f"얼굴 모델이 없습니다: {model_path}. ART_FACE_MODEL_PATH로 설치한 모델을 지정하세요. 자동 다운로드하지 않습니다."
    )


def _ordered_oval_points(
    landmarks: list,
    connections: list,
    width: int,
    height: int,
) -> np.ndarray:
    """FACE_LANDMARKS_FACE_OVAL 연결을 순서 있는 얼굴 윤곽 다각형으로 만듭니다."""
    adj: dict[int, list[int]] = {}
    for conn in connections:
        adj.setdefault(conn.start, []).append(conn.end)
        adj.setdefault(conn.end, []).append(conn.start)

    start_idx = connections[0].start
    ordered = [start_idx]
    prev = -1
    curr = start_idx
    while len(ordered) <= len(adj):
        neighbors = [n for n in adj.get(curr, []) if n != prev]
        if not neighbors:
            break
        nxt = neighbors[0]
        if nxt == start_idx:
            break
        if nxt in ordered:
            raise ValueError("얼굴 윤곽 연결이 올바른 폐곡선이 아닙니다.")
        ordered.append(nxt)
        prev, curr = curr, nxt

    pts = [
        [int(round(landmarks[i].x * width)), int(round(landmarks[i].y * height))]
        for i in ordered
    ]
    return np.array(pts, dtype=np.int32)


@dataclass
class LineartMflLdConfig:
    """얼굴 Canny와 비얼굴 LineartDetector의 합성 설정입니다."""

    face_model_path: Path = DEFAULT_FACE_MODEL_PATH
    face_model_url: str = DEFAULT_FACE_MODEL_URL
    num_faces: int = 1
    face_canny_low: int = 22
    face_canny_high: int = 65
    face_bilateral_d: int = 5
    face_bilateral_sigma: float = 40.0
    face_line_thickness: int = 2
    mask_dilate_px: int = 6
    include_hair_roi: bool = True
    hair_top_extend_ratio: float = 0.45
    hair_side_extend_ratio: float = 0.15
    paper: str | None = None
    dl_config: LineartDLConfig = field(default_factory=LineartDLConfig)


class LineartConverterMflLd:
    """실제 얼굴 영역을 검출하고 영역별 선화 결과를 합성합니다."""

    def __init__(self, config: LineartMflLdConfig | None = None) -> None:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self.mp, self.vision = mp, vision
        self.config = config or LineartMflLdConfig()
        model_path = _ensure_face_model(
            Path(self.config.face_model_path),
            self.config.face_model_url,
        )
        base_options = mp_python.BaseOptions(model_asset_path=str(model_path))
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,
            num_faces=self.config.num_faces,
        )
        self.landmarker = vision.FaceLandmarker.create_from_options(options)
        try:
            self.dl_converter = LineartConverterDL(self.config.dl_config)
        except Exception:
            self.landmarker.close()
            raise

    def convert(
        self,
        image: ImageInput,
        *,
        paper: str | None = None,
        bgr_input: bool = False,
    ) -> Image.Image:
        """사진을 얼굴 Canny와 비얼굴 DL이 합성된 선화로 변환합니다."""
        pil_rgb = load_pil_rgb(image, bgr_input=bgr_input)

        # 얼굴이 없을 때도 사용할 전체 DL 선화를 먼저 생성합니다.
        dl_img = self.dl_converter.convert(pil_rgb, paper=None)
        dl_arr = np.array(dl_img, dtype=np.uint8)
        h, w = dl_arr.shape[:2]

        # DL 결과와 크기를 맞춘 RGB 영상에서 얼굴 랜드마크를 검출합니다.
        aligned_rgb = np.array(pil_rgb.resize((w, h), Image.Resampling.LANCZOS))
        mp_image = self.mp.Image(
            image_format=self.mp.ImageFormat.SRGB, data=aligned_rgb
        )
        detection = self.landmarker.detect(mp_image)

        target_paper = self.config.paper if paper is None else paper
        if not detection.face_landmarks:
            return pad_to_paper_ratio(dl_img, target_paper)

        # 얼굴 윤곽과 선택한 머리카락 확장 영역의 마스크를 만듭니다.
        face_mask = np.zeros((h, w), dtype=np.uint8)
        conns = self.vision.FaceLandmarksConnections
        for landmarks in detection.face_landmarks:
            oval_pts = _ordered_oval_points(
                landmarks, conns.FACE_LANDMARKS_FACE_OVAL, w, h
            )
            cv2.fillPoly(face_mask, [oval_pts], 255)
            if self.config.include_hair_roi:
                x, y, fw, fh = cv2.boundingRect(oval_pts)
                top_ext = int(round(fh * self.config.hair_top_extend_ratio))
                side_ext = int(round(fw * self.config.hair_side_extend_ratio))
                cx = x + fw // 2
                cy = max(0, y + int(round(fh * 0.28)) - top_ext // 2)
                rx = max(1, fw // 2 + side_ext)
                ry = max(1, int(round(fh * 0.45)) + top_ext // 2)
                cv2.ellipse(face_mask, (cx, cy), (rx, ry), 0, 0, 360, 255, -1)

        if self.config.mask_dilate_px > 0:
            k = self.config.mask_dilate_px * 2 + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
            face_mask = cv2.dilate(face_mask, kernel)

        combined = compose_face_lineart(aligned_rgb, dl_arr, face_mask, self.config)
        return pad_to_paper_ratio(combined, target_paper)

    def close(self):
        self.landmarker.close()

    def convert_to_file(
        self,
        input_path: str | Path,
        output_path: str | Path,
        **kwargs,
    ) -> Path:
        """입력 파일을 변환하고 혼합 선화를 지정한 출력에 저장합니다."""
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = self.convert(input_path, **kwargs)
        result.save(out_path)
        return out_path


def compose_face_lineart(rgb, dl_arr, face_mask, config):
    """원본의 얼굴 Canny와 비얼굴 DL 결과 합성. 모델 추론과 별도 검증합니다."""
    # 참고 코드의 얼굴 전용 Canny 처리를 적용합니다.
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    face_smooth = cv2.bilateralFilter(
        gray,
        d=config.face_bilateral_d,
        sigmaColor=config.face_bilateral_sigma,
        sigmaSpace=config.face_bilateral_sigma,
    )
    face_edges = cv2.Canny(
        face_smooth,
        config.face_canny_low,
        config.face_canny_high,
    )
    if config.face_line_thickness > 1:
        t = config.face_line_thickness
        k = np.ones((t, t), dtype=np.uint8)
        face_edges = cv2.dilate(face_edges, k, iterations=1)
    face_sketch = 255 - face_edges

    # 얼굴 마스크 안은 Canny, 밖은 DL 선화를 유지합니다.
    combined = np.where(face_mask > 0, face_sketch, dl_arr).astype(np.uint8)
    return Image.fromarray(combined, mode="L")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="MediaPipe 얼굴 Canny + 비얼굴 LineartDetector"
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    converter = LineartConverterMflLd()
    try:
        converter.convert_to_file(args.input, args.output)
    finally:
        converter.close()


if __name__ == "__main__":
    main()
