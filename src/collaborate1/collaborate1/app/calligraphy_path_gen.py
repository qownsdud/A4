#!/usr/bin/env python3
"""한글 캘리그라피 폰트에서 로봇용 (X, Y, dZ) 획 경로를 생성하는 스크립트.

사용 예시:
    python3 calligraphy_path_gen.py --text "안녕" --preview preview.png --out paths.json
"""

import argparse
import json
from pathlib import Path
from typing import List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import distance_transform_edt
from skimage.morphology import skeletonize

DEFAULT_FONT = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"


def render_text_mask(
    text: str,
    font_path: str,
    font_size: int = 220,
    padding: int = 40,
) -> np.ndarray:
    """텍스트를 이진 마스크(True=글자, False=배경)로 렌더링합니다."""
    font = ImageFont.truetype(font_path, font_size)
    bbox = font.getbbox(text)
    width = (bbox[2] - bbox[0]) + padding * 2
    height = (bbox[3] - bbox[1]) + padding * 2

    img = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(img)
    draw.text((padding - bbox[0], padding - bbox[1]), text, fill=255, font=font)
    return np.array(img) > 127


def trace_strokes(
    skel: np.ndarray,
    dist: np.ndarray,
    min_len: int = 10,
) -> List[List[Tuple[float, float, float]]]:
    """1픽셀 스켈레톤을 따라가며 순서가 있는 획[(x_px, y_px, radius_px), ...]을 추출합니다."""
    visited = np.zeros_like(skel, dtype=bool)
    h, w = skel.shape
    neighbors = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    ]

    def unvisited_neighbors(r: int, c: int) -> List[Tuple[int, int]]:
        result = []
        for dr, dc in neighbors:
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and skel[nr, nc] and not visited[nr, nc]:
                result.append((nr, nc))
        return result

    ys, xs = np.where(skel)
    degree = np.zeros_like(skel, dtype=int)
    for r, c in zip(ys, xs):
        degree[r, c] = sum(
            1
            for dr, dc in neighbors
            if 0 <= r + dr < h and 0 <= c + dc < w and skel[r + dr, c + dc]
        )

    # 끝점(degree == 1)을 먼저 시작점으로 두고, 왼쪽->오른쪽, 위->아래 순으로 정렬
    endpoints = sorted(
        [(int(r), int(c)) for r, c in zip(ys, xs) if degree[r, c] == 1],
        key=lambda p: (p[1], p[0]),
    )
    start_candidates = endpoints + [(int(r), int(c)) for r, c in zip(ys, xs)]

    strokes: List[List[Tuple[float, float, float]]] = []
    for sr, sc in start_candidates:
        if visited[sr, sc]:
            continue
        stroke: List[Tuple[float, float, float]] = []
        curr = (sr, sc)
        while curr is not None:
            r, c = curr
            visited[r, c] = True
            stroke.append((float(c), float(r), float(dist[r, c])))
            nxt = unvisited_neighbors(r, c)
            curr = nxt[0] if nxt else None

        if len(stroke) >= min_len:
            strokes.append(stroke)

    return strokes


def map_to_robot_paths(
    strokes: List[List[Tuple[float, float, float]]],
    img_shape: Tuple[int, int],
    target_width_mm: float = 80.0,
    z_min_press: float = -0.5,
    z_max_press: float = -4.0,
    sample_step: int = 4,
    contrast_gamma: float = 1.6,
) -> List[List[Tuple[float, float, float]]]:
    """픽셀 획 데이터를 로봇 상대 좌표 (x_mm, y_mm, dz_mm) 리스트로 변환합니다."""
    if not strokes:
        return []

    _, img_w = img_shape
    px_to_mm = target_width_mm / max(img_w, 1)
    radii = [pt[2] for s in strokes for pt in s]
    min_radius = min(radii)
    max_radius = max(radii)
    span = max(max_radius - min_radius, 1e-6)

    # 첫 번째 획의 시작점을 원점(0, 0) 기준으로 맞추기 위해 오프셋 계산
    origin_x = strokes[0][0][0]
    origin_y = strokes[0][0][1]

    robot_paths: List[List[Tuple[float, float, float]]] = []
    for stroke in strokes:
        sampled = stroke[::sample_step]
        if stroke[-1] != sampled[-1]:
            sampled.append(stroke[-1])

        waypoints: List[Tuple[float, float, float]] = []
        for x_px, y_px, radius_px in sampled:
            x_mm = (x_px - origin_x) * px_to_mm
            # 이미지 Y축(아래)을 로봇 평면 Y축(위) 방향으로 반전
            y_mm = -(y_px - origin_y) * px_to_mm
            norm = min(max((radius_px - min_radius) / span, 0.0), 1.0)
            ratio = norm ** contrast_gamma
            dz_mm = z_min_press + ratio * (z_max_press - z_min_press)
            waypoints.append((round(x_mm, 2), round(y_mm, 2), round(dz_mm, 2)))

        robot_paths.append(waypoints)

    return robot_paths


def save_preview(
    mask: np.ndarray,
    strokes: List[List[Tuple[float, float, float]]],
    output_path: str,
) -> None:
    """원본 폰트 마스크 위에 추출된 중심선과 두께 정보를 시각화해 저장합니다."""
    h, w = mask.shape
    vis = Image.new("RGB", (w, h), (255, 255, 255))
    mask_img = Image.fromarray((~mask).astype(np.uint8) * 200 + 55)
    vis.paste(mask_img.convert("RGB"))
    draw = ImageDraw.Draw(vis)

    for stroke in strokes:
        pts = [(x, y) for x, y, _ in stroke]
        if len(pts) >= 2:
            draw.line(pts, fill=(220, 40, 40), width=2)
        if pts:
            sx, sy = pts[0]
            draw.ellipse((sx - 3, sy - 3, sx + 3, sy + 3), fill=(0, 140, 255))

    vis.save(output_path)


def generate_calligraphy_paths(
    text: str,
    font_path: str = DEFAULT_FONT,
    font_size: int = 220,
    target_width_mm: float = 80.0,
    z_min_press: float = -0.5,
    z_max_press: float = -4.0,
    min_len: int = 12,
    sample_step: int = 4,
    preview_path: str | None = None,
) -> List[List[Tuple[float, float, float]]]:
    """문자열을 받아 로봇용 (x_mm, y_mm, dz_mm) 획 경로 리스트를 반환합니다."""
    mask = render_text_mask(text, font_path=font_path, font_size=font_size)
    skel = skeletonize(mask)
    dist = distance_transform_edt(mask)
    strokes = trace_strokes(skel, dist, min_len=min_len)

    if preview_path:
        save_preview(mask, strokes, preview_path)

    return map_to_robot_paths(
        strokes,
        img_shape=mask.shape,
        target_width_mm=target_width_mm,
        z_min_press=z_min_press,
        z_max_press=z_max_press,
        sample_step=sample_step,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="한글 캘리그라피 로봇 경로 생성기")
    parser.add_argument("--text", default="한글", help="그릴 문자열 (기본값: 한글)")
    parser.add_argument("--font", default=DEFAULT_FONT, help="TTF/OTF/TTC 폰트 파일 경로")
    parser.add_argument("--font-size", type=int, default=220, help="렌더링 폰트 크기(px)")
    parser.add_argument("--width-mm", type=float, default=80.0, help="전체 폭(mm)")
    parser.add_argument("--z-min", type=float, default=-0.5, help="가장 얇은 획의 Z 오프셋(mm)")
    parser.add_argument("--z-max", type=float, default=-4.0, help="가장 굵은 획의 Z 오프셋(mm)")
    parser.add_argument("--step", type=int, default=4, help="스켈레톤 샘플링 간격(px)")
    parser.add_argument("--preview", default="", help="미리보기 이미지 저장 경로 (예: preview.png)")
    parser.add_argument("--out", default="", help="JSON 경로 저장 파일 (예: paths.json)")
    args = parser.parse_args()

    paths = generate_calligraphy_paths(
        text=args.text,
        font_path=args.font,
        font_size=args.font_size,
        target_width_mm=args.width_mm,
        z_min_press=args.z_min,
        z_max_press=args.z_max,
        sample_step=args.step,
        preview_path=args.preview or None,
    )

    print(f"총 {len(paths)}개의 획 생성 완료")
    for idx, stroke in enumerate(paths, start=1):
        print(f"  획 {idx}: {len(stroke)}개 포인트 | 시작={stroke[0]} -> 끝={stroke[-1]}")

    if args.out:
        out_file = Path(args.out)
        out_file.write_text(json.dumps(paths, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 저장 완료: {out_file}")


if __name__ == "__main__":
    main()
