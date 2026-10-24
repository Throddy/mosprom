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


def sample_frames(video: Path, start: float, end: float) -> list[np.ndarray]:
    """Кадры с шагом 0,1 с в интервале start…end, время в секундах от начала видео."""
    capture = cv2.VideoCapture(str(video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    if not fps:
        raise SystemExit(f"не удалось прочитать fps видео {video}")
    frames, index, taken = [], 0, 0
    while start + taken * STEP_SECONDS <= end + 1e-6:
        ok, frame = capture.read()
        if not ok:
            break
        if index / fps >= start + taken * STEP_SECONDS - 1e-6:
            frames.append(frame)
            taken += 1
        index += 1
    capture.release()
    return frames


def detector_with_pose_conf(conf: float) -> Detector:
    load = yaml.safe_load

    def load_with_conf(text: str) -> dict:
        config = load(text)
        config["models"]["pose"]["conf"] = conf
        return config

    # Порог подменяется при чтении configs/models.yaml: детектор собирается как при правке файла.
    with mock.patch.object(yaml, "safe_load", load_with_conf):
        return create_detector("onnx")


def main() -> None:
    parser = argparse.ArgumentParser(description="Доля кадров с найденным человеком")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--conf", type=float, required=True)
    args = parser.parse_args()

    frames = sample_frames(args.video, args.start, args.end)
    if not frames:
        raise SystemExit(f"нет кадров в интервале {args.start}–{args.end} с: {args.video}")
    detector = detector_with_pose_conf(args.conf)
    best_conf = []
    for frame in frames:
        persons = [d.conf for d in detector.infer([frame])[0] if d.cls == "person"]
        if persons:
            best_conf.append(max(persons))
    share = len(best_conf) / len(frames)
    mean_conf = float(np.mean(best_conf)) if best_conf else 0.0
    print(f"{args.video.name} conf={args.conf}: кадров {len(frames)}, с человеком "
          f"{len(best_conf)}, доля {share:.2f}, средняя уверенность лучшего person {mean_conf:.2f}")


if __name__ == "__main__":
    main()
