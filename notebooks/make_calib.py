import argparse
import sys
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ml.prepost import preprocess  # noqa: E402

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv"}
FRAMES_PER_VIDEO = 25


def even_indices(total: int, count: int) -> list[int]:
    if total <= 0 or count <= 0:
        return []
    return sorted({round(x) for x in np.linspace(0, total - 1, min(count, total))})


def iter_video(path: Path, count: int) -> Iterator[tuple[np.ndarray, int]]:
    capture = cv2.VideoCapture(str(path))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    for index in even_indices(total, count):
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        if ok:
            yield frame, index
    capture.release()


def iter_frames(src: Path, count: int) -> Iterator[tuple[np.ndarray, Path, int]]:
    files = sorted(p for p in src.rglob("*") if p.is_file())
    videos = [p for p in files if p.suffix.lower() in VIDEO_EXTS]
    images = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
    produced = 0
    for video in videos:
        for frame, index in iter_video(video, min(FRAMES_PER_VIDEO, count - produced)):
            produced += 1
            yield frame, video, index
    for i in even_indices(len(images), count - produced):
        yield cv2.imread(str(images[i])), images[i], 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=250)
    parser.add_argument("--tensors", action="store_true")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, (frame, source, index) in enumerate(iter_frames(args.src, args.count)):
        name = f"{i:04d}.jpg"
        cv2.imwrite(str(args.out / name), frame)
        if args.tensors:
            tensor, _ = preprocess(frame)
            np.save(args.out / f"{i:04d}.npy", tensor)
        lines.append(f"{name},{source},{index}")
    (args.out / "list.txt").write_text("\n".join(lines) + "\n")
    print(f"кадров: {len(lines)}, папка: {args.out}")


if __name__ == "__main__":
    main()
