"""Пережать видео для демо-стенда: высота --height, частота --fps, без звука, кодек mp4v.

python scripts/transcode.py --src DIR --dst DIR [--height 720] [--fps 10]
"""
import argparse
import sys
from pathlib import Path

import cv2

VIDEO_SUFFIXES = {".mov", ".MOV", ".mp4", ".MP4"}


def transcode(src: Path, dst: Path, height: int, fps: float) -> int:
    """Возвращает число записанных кадров."""
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise OSError(f"видео не открывается: {src}")
    step = (cap.get(cv2.CAP_PROP_FPS) or 25.0) / fps
    writer = None
    index, written, next_pos = 0, 0, 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index >= next_pos:
            h, w = frame.shape[:2]
            size = (round(w * height / h / 2) * 2, height)
            if writer is None:
                writer = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
            writer.write(cv2.resize(frame, size, interpolation=cv2.INTER_AREA))
            written += 1
            next_pos += step
        index += 1
    cap.release()
    if writer is not None:
        writer.release()
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Пережать видео для демо-стенда")
    parser.add_argument("--src", required=True)
    parser.add_argument("--dst", required=True)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=float, default=10.0)
    args = parser.parse_args()
    src, dst = Path(args.src), Path(args.dst)
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(p for p in src.iterdir() if p.suffix in VIDEO_SUFFIXES):
        out = dst / f"{path.stem}.mp4"
        frames = transcode(path, out, args.height, args.fps)
        print(f"{path.name}: {path.stat().st_size / 1e6:.1f} МБ -> {out.name}: {out.stat().st_size / 1e6:.1f} МБ, "
              f"{frames} кадров")
    return 0


if __name__ == "__main__":
    sys.exit(main())
