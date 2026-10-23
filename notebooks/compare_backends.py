import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schemas import BBox, Detection  # noqa: E402
from ml import create_detector  # noqa: E402

FRAME_COUNT = 20
MIN_IOU = 0.5


def iou(a: BBox, b: BBox) -> float:
    inter_w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    inter_h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = inter_w * inter_h
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match(ref: list[Detection], got: list[Detection]) -> list[tuple[int, int, float]]:
    candidates = sorted(((iou(r.bbox, g.bbox), i, j)
                         for i, r in enumerate(ref) for j, g in enumerate(got) if r.cls == g.cls),
                        reverse=True)
    used_ref, used_got, pairs = set(), set(), []
    for value, i, j in candidates:
        if value < MIN_IOU:
            break
        if i in used_ref or j in used_got:
            continue
        used_ref.add(i)
        used_got.add(j)
        pairs.append((i, j, value))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=Path, default=Path("data/videos/calib"))
    args = parser.parse_args()

    paths = sorted(args.frames.glob("*.jpg"))[:FRAME_COUNT]
    frames = [cv2.imread(str(path)) for path in paths]
    results = {backend: create_detector(backend).infer(frames) for backend in ("onnx", "linq")}

    pair_ious, kpt_offsets = [], []
    unmatched = {"onnx": 0, "linq": 0}
    for ref, got in zip(results["onnx"], results["linq"]):
        pairs = match(ref, got)
        pair_ious += [value for _, _, value in pairs]
        kpt_offsets += [
            float(np.linalg.norm(ref[i].kpts[:, :2] - got[j].kpts[:, :2], axis=1).mean())
            for i, j, _ in pairs if ref[i].cls == "person"
        ]
        unmatched["onnx"] += len(ref) - len(pairs)
        unmatched["linq"] += len(got) - len(pairs)

    total_onnx = sum(len(dets) for dets in results["onnx"])
    print(f"кадров: {len(frames)}, объектов onnx: {total_onnx}, "
          f"linq: {sum(len(dets) for dets in results['linq'])}")
    print(f"пар: {len(pair_ious)}, IoU среднее {np.mean(pair_ious):.3f}, "
          f"минимальное {np.min(pair_ious):.3f}" if pair_ious else "пар: 0")
    print(f"без пары: onnx {unmatched['onnx']}, linq {unmatched['linq']}")
    print(f"смещение точек person: {np.mean(kpt_offsets):.2f} px" if kpt_offsets
          else "смещение точек person: пар person нет")


if __name__ == "__main__":
    main()
