import argparse
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schemas import Detection  # noqa: E402
from make_calib import IMAGE_EXTS, even_indices, iter_video  # noqa: E402
from ml import create_detector  # noqa: E402

VEHICLES = ("car", "truck", "bus")
SAVED_FRAMES = 5
COLORS = {"person": (0, 200, 0), "car": (255, 128, 0), "truck": (0, 0, 255), "bus": (0, 200, 255)}


def load_frames(src: Path, count: int) -> list[np.ndarray]:
    if src.is_file():
        return [frame for frame, _ in iter_video(src, count)]
    images = sorted(p for p in src.rglob("*") if p.suffix.lower() in IMAGE_EXTS)
    return [cv2.imread(str(images[i])) for i in even_indices(len(images), count)]


def draw(frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
    canvas = frame.copy()
    thickness = max(2, frame.shape[1] // 640)
    for det in detections:
        x1, y1, x2, y2 = (int(v) for v in det.bbox)
        color = COLORS.get(det.cls, (255, 255, 255))
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)
        cv2.putText(canvas, f"{det.cls} {det.conf:.2f}", (x1, max(0, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, thickness / 2, color, thickness)
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/videos/ml5"))
    parser.add_argument("--count", type=int, default=50)
    args = parser.parse_args()

    frames = load_frames(args.src, args.count)
    detector = create_detector("onnx")
    results = [detector.infer([frame])[0] for frame in frames]

    objects = Counter(det.cls for dets in results for det in dets if det.cls in VEHICLES)
    frames_with = Counter(cls for dets in results for cls in {d.cls for d in dets} & set(VEHICLES))
    hit = sum(any(det.cls in VEHICLES for det in dets) for dets in results)
    print(f"источник: {args.src}, кадров: {len(frames)}")
    print(f"кадров с car/truck/bus: {hit}, доля {hit / len(frames):.2f}")
    print(f"объектов по классам: {dict(objects)}")
    print(f"кадров по классам: {dict(frames_with)}")

    args.out.mkdir(parents=True, exist_ok=True)
    for i in even_indices(len(frames), SAVED_FRAMES):
        cv2.imwrite(str(args.out / f"forklift_{i:02d}.jpg"), draw(frames[i], results[i]))
    print(f"кадры с боксами: {args.out}")


if __name__ == "__main__":
    main()
