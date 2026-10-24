"""Склеить видео в один ролик для камеры демо-стенда: кадр 1280x720 с полями, между видео 1 с чёрного.

python scripts/make_reel.py --dst data/videos/demo/reel.mp4 [--height 720] [--fps 10] VIDEO...
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

GAP_SECONDS = 1.0  # чёрные кадры между видео, чтобы трекер не склеивал людей из разных сцен


def fit(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    """Вписать кадр в width x height без растяжения, с чёрными полями."""
    h, w = frame.shape[:2]
    scale = min(width / w, height / h)
    nw, nh = round(w * scale), round(h * scale)
    canvas = np.zeros((height, width, 3), np.uint8)
    x, y = (width - nw) // 2, (height - nh) // 2
    canvas[y:y + nh, x:x + nw] = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser(description="Склеить видео в ролик для демо-стенда")
    parser.add_argument("--dst", required=True)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("videos", nargs="+")
    args = parser.parse_args()
    height = args.height
    width = round(height * 16 / 9 / 2) * 2
    Path(args.dst).parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(args.dst, cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (width, height))
    black = np.zeros((height, width, 3), np.uint8)
    total = 0
    for i, video in enumerate(args.videos):
        if i:
            for _ in range(round(GAP_SECONDS * args.fps)):
                writer.write(black)
                total += 1
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            print(f"make_reel: видео не открывается: {video}", file=sys.stderr)
            return 2
        step = (cap.get(cv2.CAP_PROP_FPS) or 25.0) / args.fps
        index, frames, next_pos = 0, 0, 0.0
        start = total / args.fps
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if index >= next_pos:
                writer.write(fit(frame, width, height))
                frames += 1
                total += 1
                next_pos += step
            index += 1
        cap.release()
        print(f"{Path(video).name}: {frames / args.fps:.1f} с, с {start:.1f} по {total / args.fps:.1f} с ролика")
    writer.release()
    print(f"{args.dst}: {total / args.fps:.1f} с, {width}x{height}, {args.fps:g} кадров/с")
    return 0


if __name__ == "__main__":
    sys.exit(main())
