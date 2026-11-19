"""Lightweight OpenCV-based photo-to-sketch conversion module."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image

from .utils import ImageInput, binarize_gray, load_pil_rgb, pad_to_paper_ratio

CVSketchMode = Literal["dodge", "canny", "adaptive"]


def _resolve_face_cascade_path(custom_path: str | None = None) -> Path | None:
    """Locate a Haar cascade XML file for frontal face detection."""
    candidates: list[Path] = []
    if custom_path:
        candidates.append(Path(custom_path))
    cv_data = getattr(cv2, "data", None)
    if cv_data is not None and hasattr(cv_data, "haarcascades"):
        candidates.append(Path(cv_data.haarcascades) / "haarcascade_frontalface_default.xml")
    candidates.extend([
        Path("/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"),
        Path("/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml"),
    ])
    for path in candidates:
        if path.is_file():
            return path
    return None


@dataclass
class LineartCVConfig:
    """Configuration for OpenCV-based lightweight sketch conversion."""

    mode: CVSketchMode = "canny"
    blur_ksize: int = 21
    bilateral_d: int = 9
    bilateral_sigma: float = 75.0
    canny_low: int = 50
    canny_high: int = 150
    use_face_roi: bool = True
    use_person_segmentation: bool = True
    face_bilateral_d: int = 7
    face_bilateral_sigma: float = 55.0
    face_canny_low: int = 45
    face_canny_high: int = 115
    face_line_thickness: int = 1
    face_cascade_path: str | None = None
    adaptive_block_size: int = 11
    adaptive_c: int = 4
    max_side: int | None = None
    binarize: bool = False
    paper: str | None = None


def _ensure_odd_ksize(ksize: int) -> int:
    k = max(3, int(ksize))
    return k if k % 2 == 1 else k + 1


def _resize_max_side(rgb: np.ndarray, max_side: int | None) -> np.ndarray:
    if max_side is None or max_side <= 0:
        return rgb
    h, w = rgb.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return rgb
    scale = max_side / longest
    new_w, new_h = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    return cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)


class LineartConverterCV:
    """Fast CPU-only OpenCV sketch converter supporting dodge, canny, and adaptive modes."""

    def __init__(self, config: LineartCVConfig | None = None) -> None:
        self.config = config or LineartCVConfig()

    def convert(
        self,
        image: ImageInput,
        *,
        mode: CVSketchMode | None = None,
        max_side: int | None = None,
        binarize: bool | None = None,
        paper: str | None = None,
        bgr_input: bool = False,
    ) -> Image.Image:
        """Convert an input photo to a grayscale sketch PIL Image."""
        pil_rgb = load_pil_rgb(image, bgr_input=bgr_input)
        rgb = np.array(pil_rgb)
        rgb = _resize_max_side(
            rgb, self.config.max_side if max_side is None else max_side
        )
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

        sketch_mode = self.config.mode if mode is None else mode
        if sketch_mode == "dodge":
            sketch = self._dodge_sketch(gray)
        elif sketch_mode == "canny":
            sketch = self._canny_sketch(gray, rgb=rgb)
        elif sketch_mode == "adaptive":
            sketch = self._adaptive_sketch(gray)
        else:
            raise ValueError(
                f"지원하지 않는 OpenCV 변환 모드입니다: {sketch_mode}. "
                "가능 값: 'dodge', 'canny', 'adaptive'"
            )

        do_binarize = self.config.binarize if binarize is None else binarize
        if do_binarize and sketch_mode != "canny":
            sketch = binarize_gray(sketch)

        target_paper = self.config.paper if paper is None else paper
        return pad_to_paper_ratio(Image.fromarray(sketch, mode="L"), target_paper)

    def _dodge_sketch(self, gray: np.ndarray) -> np.ndarray:
        """Pencil-sketch effect via grayscale inversion, Gaussian blur, and color dodge."""
        k = _ensure_odd_ksize(self.config.blur_ksize)
        inverted = 255 - gray
        blurred = cv2.GaussianBlur(inverted, (k, k), 0)
        return cv2.divide(gray, 255 - blurred, scale=256.0)

    def _detect_faces(self, gray: np.ndarray):
        if not self.config.use_face_roi:
            return ()
        cascade_path = _resolve_face_cascade_path(self.config.face_cascade_path)
        if cascade_path is None:
            return ()
        classifier = cv2.CascadeClassifier(str(cascade_path))
        if classifier.empty():
            return ()
        min_dim = max(24, min(gray.shape[:2]) // 10)
        faces = classifier.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(min_dim, min_dim)
        )
        return faces if len(faces) > 0 else ()

    def _build_face_roi_mask(self, shape: tuple[int, int], faces) -> np.ndarray:
        mask = np.zeros(shape, dtype=np.uint8)
        for x, y, fw, fh in faces:
            cx = int(x + fw * 0.5)
            cy = int(y + fh * 0.42)
            rx = max(1, int(round(fw * 0.48)))
            ry = max(1, int(round(fh * 0.65)))
            cv2.ellipse(mask, (cx, cy), (rx, ry), 0, 0, 360, 255, -1)
        return mask

    def _build_person_mask(self, rgb: np.ndarray, faces) -> np.ndarray | None:
        """얼굴 위치를 기준으로 GrabCut을 수행해 인물 전경(머리·몸통) 마스크를 분리합니다."""
        if not self.config.use_person_segmentation or len(faces) == 0:
            return None
        h, w = rgb.shape[:2]
        scale = min(1.0, 256.0 / max(h, w))
        sw, sh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        small = cv2.resize(rgb, (sw, sh), interpolation=cv2.INTER_AREA)

        gc_mask = np.full((sh, sw), cv2.GC_PR_BGD, dtype=np.uint8)
        b = max(2, int(min(sh, sw) * 0.04))
        gc_mask[:b, :] = cv2.GC_BGD
        gc_mask[-b:, :] = cv2.GC_BGD
        gc_mask[:, :b] = cv2.GC_BGD
        gc_mask[:, -b:] = cv2.GC_BGD

        for x, y, fw, fh in faces:
            sx, sy, sfw, sfh = x * scale, y * scale, fw * scale, fh * scale
            px1 = max(0, int(sx - sfw * 0.90))
            px2 = min(sw, int(sx + sfw * 1.55))
            py1 = max(0, int(sy - sfh * 0.45))
            gc_mask[py1:sh, px1:px2] = cv2.GC_PR_FGD

            cx, cy = int(sx + sfw * 0.5), int(sy + sfh * 0.5)
            cv2.ellipse(
                gc_mask,
                (cx, cy),
                (max(1, int(sfw * 0.32)), max(1, int(sfh * 0.40))),
                0, 0, 360, cv2.GC_FGD, -1,
            )
            tx1 = max(0, int(sx - sfw * 0.15))
            tx2 = min(sw, int(sx + sfw * 1.15))
            ty1 = min(sh - 1, int(sy + sfh * 1.15))
            ty2 = min(sh, int(sy + sfh * 2.20))
            if ty2 > ty1 and tx2 > tx1:
                gc_mask[ty1:ty2, tx1:tx2] = cv2.GC_FGD

        bgd_model = np.zeros((1, 65), np.float64)
        fgd_model = np.zeros((1, 65), np.float64)
        try:
            cv2.grabCut(small, gc_mask, None, bgd_model, fgd_model, 3, cv2.GC_INIT_WITH_MASK)
        except cv2.error:
            return None

        fg_small = np.where((gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        fg_small = cv2.morphologyEx(fg_small, cv2.MORPH_CLOSE, k)
        fg_small = cv2.morphologyEx(fg_small, cv2.MORPH_OPEN, k)
        fg_mask = cv2.resize(fg_small, (w, h), interpolation=cv2.INTER_NEAREST)
        return cv2.dilate(fg_mask, np.ones((7, 7), np.uint8), iterations=1)

    def _canny_sketch(self, gray: np.ndarray, rgb: np.ndarray | None = None) -> np.ndarray:
        """인물 전경은 깔끔하게, 배경 잡음·보케는 억제하여 윤곽선을 추출합니다."""
        bg_smoothed = cv2.bilateralFilter(
            gray,
            d=self.config.bilateral_d,
            sigmaColor=self.config.bilateral_sigma,
            sigmaSpace=self.config.bilateral_sigma,
        )
        edges = cv2.Canny(bg_smoothed, self.config.canny_low, self.config.canny_high)

        faces = self._detect_faces(gray)
        if len(faces) > 0:
            if rgb is not None:
                person_mask = self._build_person_mask(rgb, faces)
                if person_mask is not None:
                    # 배경은 약하게(높은 임계값 + 큰 윤곽선만 유지) 남겨 과도한 잡음만 억제합니다.
                    bg_soft = cv2.GaussianBlur(gray, (7, 7), 1.8)
                    bg_soft = cv2.bilateralFilter(bg_soft, d=9, sigmaColor=85, sigmaSpace=85)
                    bg_edges = cv2.Canny(
                        bg_soft,
                        min(220, int(self.config.canny_low * 1.9)),
                        min(350, int(self.config.canny_high * 1.6)),
                    )
                    bg_only = np.where(person_mask == 0, bg_edges, 0)
                    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(bg_only, connectivity=8)
                    keep_bg = np.zeros_like(bg_only)
                    for lbl in range(1, num_labels):
                        area = stats[lbl, cv2.CC_STAT_AREA]
                        bw = stats[lbl, cv2.CC_STAT_WIDTH]
                        bh = stats[lbl, cv2.CC_STAT_HEIGHT]
                        if area >= 28 or max(bw, bh) >= 26:
                            keep_bg[labels == lbl] = 255
                    edges = np.where(person_mask > 0, edges, keep_bg)

            face_mask = self._build_face_roi_mask(gray.shape[:2], faces)
            # 2단계 bilateral로 피부 잡음·잔주름은 줄이고 눈/코/입/윤곽선은 선명하게 유지합니다.
            sigma1 = self.config.face_bilateral_sigma * 1.1
            sigma2 = self.config.face_bilateral_sigma * 0.85
            face_smoothed = cv2.bilateralFilter(
                gray,
                d=self.config.face_bilateral_d,
                sigmaColor=sigma1,
                sigmaSpace=sigma1,
            )
            face_smoothed = cv2.bilateralFilter(
                face_smoothed,
                d=max(3, self.config.face_bilateral_d - 2),
                sigmaColor=sigma2,
                sigmaSpace=sigma2,
            )
            face_edges = cv2.Canny(
                face_smoothed, self.config.face_canny_low, self.config.face_canny_high
            )
            if self.config.face_line_thickness > 1:
                t = self.config.face_line_thickness
                face_edges = cv2.dilate(
                    face_edges, np.ones((t, t), dtype=np.uint8), iterations=1
                )
            edges = np.where(face_mask > 0, face_edges, edges)

        return 255 - edges

    def _adaptive_sketch(self, gray: np.ndarray) -> np.ndarray:
        """High-contrast line extraction via bilateral filtering and adaptive thresholding."""
        smoothed = cv2.bilateralFilter(
            gray,
            d=self.config.bilateral_d,
            sigmaColor=self.config.bilateral_sigma,
            sigmaSpace=self.config.bilateral_sigma,
        )
        block = _ensure_odd_ksize(self.config.adaptive_block_size)
        return cv2.adaptiveThreshold(
            smoothed,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block,
            self.config.adaptive_c,
        )

    def convert_to_file(
        self,
        input_path: str | Path,
        output_path: str | Path,
        **kwargs,
    ) -> Path:
        """Convert an image file and save the resulting sketch to disk."""
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = self.convert(input_path, **kwargs)
        result.save(out_path)
        return out_path
