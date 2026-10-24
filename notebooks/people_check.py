import argparse
import json
import sys
import time
from pathlib import Path
from unittest import mock

import cv2
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.schemas import BBox, Detector  # noqa: E402
from ml import create_detector  # noqa: E402

MATCH_IOU = 0.3
TRIGGER_MAX_H = 0.2
OVERLAP = 0.2
# Вариант: (порог person, плитки rows × cols или None).
VARIANTS = {"A": (0.4, None), "B": (0.25, None), "C": (0.25, (2, 2)), "D": (0.25, (2, 3))}


def iou(a: BBox, b: BBox) -> float:
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - w * h
    return w * h / union if union > 0 else 0.0


def matched(reference: list[BBox], found: list[BBox]) -> int:
    """Пары один к одному, жадно по убыванию IoU, IoU не меньше MATCH_IOU."""
    pairs = sorted(((iou(r, f), i, j) for i, r in enumerate(reference) for j, f in enumerate(found)),
                   reverse=True)
    used_ref, used_found = set(), set()
    for value, i, j in pairs:
        if value < MATCH_IOU:
            break
        if i not in used_ref and j not in used_found:
            used_ref.add(i)
            used_found.add(j)
    return len(used_ref)


def detector_for(person_conf: float, grid: tuple[int, int] | None) -> Detector:
    load = yaml.safe_load

    def load_variant(text: str) -> dict:
        config = load(text)
        pose = config["models"]["pose"]
        pose["conf"] = person_conf
        pose.pop("tiles", None)
        if grid:
            pose["tiles"] = {"enabled": True, "rows": grid[0], "cols": grid[1],
                             "overlap": OVERLAP, "trigger_max_h": TRIGGER_MAX_H}
        return config

    # Вариант задаётся при чтении configs/models.yaml: детектор собирается как при правке файла.
    with mock.patch.object(yaml, "safe_load", load_variant):
        return create_detector("onnx")


def evaluate(name: str, frames: dict[str, object], reference: dict[str, list[BBox]],
             save_dir: Path | None) -> None:
    detector = detector_for(*VARIANTS[name])
    detector.infer([next(iter(frames.values()))])
    total_ref = total_match = extra = 0
    elapsed = 0.0
    for frame_name, image in frames.items():
        started = time.perf_counter()
        persons = [d.bbox for d in detector.infer([image])[0] if d.cls == "person"]
        elapsed += time.perf_counter() - started
        found = matched(reference[frame_name], persons)
        total_ref += len(reference[frame_name])
        total_match += found
        extra += len(persons) - found
        if save_dir and frame_name in ("00.jpg", "07.jpg", "14.jpg"):
            _save(save_dir / f"{name}_{frame_name}", image, persons)
    ms = elapsed / len(frames) * 1000
    print(f"{name}: полнота {total_match / total_ref:.2f} ({total_match} из {total_ref}), "
          f"лишних {extra}, {ms:.0f} мс на кадр, {1000 / ms:.2f} кадра/с")


def _save(path: Path, image, boxes: list[BBox]) -> None:
    canvas = image.copy()
    for x1, y1, x2, y2 in boxes:
        cv2.rectangle(canvas, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 3)
    cv2.imwrite(str(path), canvas)


def main() -> None:
    parser = argparse.ArgumentParser(description="Полнота детекции людей по эталону")
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True, help="JSON: кадр -> боксы")
    parser.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=list(VARIANTS))
    parser.add_argument("--save", type=Path, help="папка для 3 кадров с боксами каждого варианта")
    args = parser.parse_args()

    reference = json.loads(args.reference.read_text())
    frames = {name: cv2.imread(str(args.frames / name)) for name in sorted(reference)}
    if args.save:
        args.save.mkdir(parents=True, exist_ok=True)
    for name in args.variants:
        evaluate(name, frames, reference, args.save)


if __name__ == "__main__":
    main()
