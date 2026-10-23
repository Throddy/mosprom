import argparse
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from ultralytics.utils import ASSETS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schemas import Detection  # noqa: E402
from ml import create_detector  # noqa: E402

BBOX_TOLERANCE_PX = 1.0
REQUIRED_CLASSES = {"person", "bus"}


def find_errors(frames: list[np.ndarray], results: list[list[Detection]]) -> list[str]:
    if len(results) != len(frames):
        return [f"длина результата {len(results)}, ожидалось {len(frames)}"]
    errors = []
    found = {det.cls for dets in results for det in dets}
    missing = REQUIRED_CLASSES - found
    if missing:
        errors.append(f"нет классов: {sorted(missing)}")
    for i, (frame, dets) in enumerate(zip(frames, results)):
        h, w = frame.shape[:2]
        for det in dets:
            if det.cls == "person" and (det.kpts is None or det.kpts.shape != (17, 3)):
                errors.append(f"кадр {i}: у person kpts не формы (17, 3)")
            if not _bbox_inside(det.bbox, w, h):
                errors.append(f"кадр {i}: {det.cls} bbox {det.bbox} вне кадра {w}x{h}")
    return errors


def _bbox_inside(bbox: tuple[float, float, float, float], w: int, h: int) -> bool:
    x1, y1, x2, y2 = bbox
    tol = BBOX_TOLERANCE_PX
    return -tol <= x1 <= x2 <= w + tol and -tol <= y1 <= y2 <= h + tol


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True)
    args = parser.parse_args()

    image = cv2.imread(str(ASSETS / "bus.jpg"))
    frames = [image, cv2.resize(image, (640, 360))]
    detector = create_detector(args.backend)
    results = detector.infer(frames)

    for i, dets in enumerate(results):
        print(f"кадр {i} {frames[i].shape[1]}x{frames[i].shape[0]}:",
              dict(Counter(det.cls for det in dets)))
    print("last_timing, мс:", detector.last_timing)

    errors = find_errors(frames, results)
    if detector.infer([]) != []:
        errors.append("infer([]) вернул не []")
    if errors:
        print("ошибка:", "; ".join(errors))
        return 1
    print("check_detector: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
