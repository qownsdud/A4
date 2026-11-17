"""Hybrid photo-to-lineart module: MediaPipe Face ROI + Canny (face) & LineartDetector (non-face)."""

from dataclasses import dataclass, field
from pathlib import Path
import urllib.request

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
import numpy as np
from PIL import Image

from lineart_dl import LineartConverterDL, LineartDLConfig
from utils import ImageInput, load_pil_rgb, pad_to_paper_ratio

DEFAULT_FACE_MODEL_PATH = Path(__file__).resolve().parent / "models" / "face_landmarker.task"
DEFAULT_FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)


def _ensure_face_model(model_path: Path, model_url: str) -> Path:
    if model_path.is_file():
        return model_path
    model_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(model_url, model_path)
    return model_path


def _ordered_oval_points(
    landmarks: list,
    connections: list,
    width: int,
    height: int,
) -> np.ndarray:
    """Build an ordered polygon from FACE_LANDMARKS_FACE_OVAL connections."""
    adj: dict[int, list[int]] = {}
    for conn in connections:
        adj.setdefault(conn.start, []).append(conn.end)
        adj.setdefault(conn.end, []).append(conn.start)

    start_idx = connections[0].start
    ordered = [start_idx]
    prev = -1
    curr = start_idx
    while True:
        neighbors = [n for n in adj.get(curr, []) if n != prev]
        if not neighbors:
            break
        nxt = neighbors[0]
        if nxt == start_idx:
            break
        ordered.append(nxt)
        prev, curr = curr, nxt

    pts = [
        [int(round(landmarks[i].x * width)), int(round(landmarks[i].y * height))]
        for i in ordered
    ]
    return np.array(pts, dtype=np.int32)


@dataclass
class LineartMflLdConfig:
    """Configuration for MediaPipe Face ROI + Canny (face) & LineartDetector (non-face)."""

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
    """Uses MediaPipe Face Landmarker for ROI, Canny inside face ROI, and LineartDetector outside."""

    def __init__(self, config: LineartMflLdConfig | None = None) -> None:
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
        self.dl_converter = LineartConverterDL(self.config.dl_config)

    def convert(
        self,
        image: ImageInput,
        *,
        paper: str | None = None,
        bgr_input: bool = False,
    ) -> Image.Image:
        """Convert photo to hybrid line art (Canny on face ROI + LineartDetector outside)."""
        pil_rgb = load_pil_rgb(image, bgr_input=bgr_input)

        # 1. Extract non-face (and fallback) line art via LineartDetector
        dl_img = self.dl_converter.convert(pil_rgb, paper=None)
        dl_arr = np.array(dl_img, dtype=np.uint8)
        h, w = dl_arr.shape[:2]

        # 2. Detect face landmarks on RGB aligned to dl_arr dimensions
        aligned_rgb = np.array(pil_rgb.resize((w, h), Image.Resampling.LANCZOS))
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=aligned_rgb)
        detection = self.landmarker.detect(mp_image)

        target_paper = self.config.paper if paper is None else paper
        if not detection.face_landmarks:
            return pad_to_paper_ratio(dl_img, target_paper)

        # 3. Build face ROI mask using MediaPipe FACE_OVAL
        face_mask = np.zeros((h, w), dtype=np.uint8)
        conns = vision.FaceLandmarksConnections
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

        # 4. Run face Canny edge detection (from the pasted face_roi Canny logic)
        gray = cv2.cvtColor(aligned_rgb, cv2.COLOR_RGB2GRAY)
        face_smooth = cv2.bilateralFilter(
            gray,
            d=self.config.face_bilateral_d,
            sigmaColor=self.config.face_bilateral_sigma,
            sigmaSpace=self.config.face_bilateral_sigma,
        )
        face_edges = cv2.Canny(
            face_smooth,
            self.config.face_canny_low,
            self.config.face_canny_high,
        )
        if self.config.face_line_thickness > 1:
            t = self.config.face_line_thickness
            k = np.ones((t, t), dtype=np.uint8)
            face_edges = cv2.dilate(face_edges, k, iterations=1)
        face_sketch = 255 - face_edges

        # 5. Composite: Canny sketch inside face ROI, LineartDetector outside
        combined = np.where(face_mask > 0, face_sketch, dl_arr).astype(np.uint8)
        return pad_to_paper_ratio(Image.fromarray(combined, mode="L"), target_paper)

    def convert_to_file(
        self,
        input_path: str | Path,
        output_path: str | Path,
        **kwargs,
    ) -> Path:
        """Convert an image file and save the hybrid line art to disk."""
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = self.convert(input_path, **kwargs)
        result.save(out_path)
        return out_path


if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(
        description="MediaPipe Face ROI(Canny) + LineartDetector(비얼굴) 하이브리드 선화 변환"
    )
    parser.add_argument("--input", required=True, help="입력 이미지 경로")
    parser.add_argument("--output-dir", default="outputs", help="출력 디렉토리")
    parser.add_argument("--canny-low", type=int, default=22, help="얼굴 Canny low (기본: 22)")
    parser.add_argument("--canny-high", type=int, default=65, help="얼굴 Canny high (기본: 65)")
    parser.add_argument(
        "--paper",
        choices=["none", "a4", "postcard", "square"],
        default="none",
        help="용지 비율 패딩",
    )
    args = parser.parse_args()

    paper_val = None if args.paper == "none" else args.paper
    t_load = time.perf_counter()
    converter = LineartConverterMflLd(
        LineartMflLdConfig(
            face_canny_low=args.canny_low,
            face_canny_high=args.canny_high,
            paper=paper_val,
        )
    )
    load_sec = time.perf_counter() - t_load

    in_path = Path(args.input)
    out_path = Path(args.output_dir) / f"{in_path.stem}_mfl_ld.png"
    t_inf = time.perf_counter()
    converter.convert_to_file(in_path, out_path)
    inf_sec = time.perf_counter() - t_inf

    print(
        f"[MFL(Canny)+LD ({converter.dl_converter.device})] "
        f"모델 로드: {load_sec:.2f} s | 추론: {inf_sec:.2f} s -> {out_path}"
    )
