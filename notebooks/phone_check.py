import argparse
import sys
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.schemas import Detector  # noqa: E402
from ml import create_detector  # noqa: E402

STEP_SECONDS = 0.1


def sample_frames(video: Path) -> list[tuple[float, np.ndarray]]:
    """Кадры всего видео с шагом 0,1 с: (время от начала видео в секундах, кадр BGR)."""
    capture = cv2.VideoCapture(str(video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    if not fps:
        raise SystemExit(f"не удалось прочитать fps видео {video}")
    frames, index, taken = [], 0, 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if index / fps >= taken * STEP_SECONDS - 1e-6:
            frames.append((taken * STEP_SECONDS, frame))
            taken += 1
        index += 1
    capture.release()
    return frames


def detector_with_phone_conf(conf: float) -> Detector:
    load = yaml.safe_load

    def load_with_conf(text: str) -> dict:
        config = load(text)
        config["models"]["det"]["class_conf"]["phone"] = conf
        return config

    # Порог подменяется при чтении configs/models.yaml: детектор собирается как при правке файла.
    with mock.patch.object(yaml, "safe_load", load_with_conf):
        return create_detector("onnx")


def share(found: list[bool]) -> str:
    return f"{sum(found) / len(found):.2f}" if found else "—"


def main() -> None:
    parser = argparse.ArgumentParser(description="Доля кадров с найденным телефоном")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--conf", type=float, required=True)
    args = parser.parse_args()

    frames = sample_frames(args.video)
    if not frames:
        raise SystemExit(f"нет кадров: {args.video}")
    detector = detector_with_phone_conf(args.conf)
    inside, outside, best_conf = [], [], []
    for ts, frame in frames:
        phones = [d.conf for d in detector.infer([frame])[0] if d.cls == "phone"]
        if phones:
            best_conf.append(max(phones))
        (inside if args.start <= ts <= args.end else outside).append(bool(phones))
    mean_conf = f"{np.mean(best_conf):.2f}" if best_conf else "—"
    print(f"{args.video.name} conf={args.conf}: кадров {len(frames)}, доля в интервале "
          f"{share(inside)}, доля вне интервала {share(outside)}, "
          f"средняя уверенность лучшего phone {mean_conf}")


if __name__ == "__main__":
    main()
