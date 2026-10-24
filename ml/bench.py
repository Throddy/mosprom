import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schemas import Detector  # noqa: E402
from ml import ROOT, create_detector  # noqa: E402
from ml.prepost import INPUT_SIZE  # noqa: E402

MODEL = "yolov8n-pose+yolov8n"
STREAMS = {"onnx": (1, 2, 4, 8), "linq": (1, 2, 4, 8, 16)}
# Для linq прогрев длиннее: программа должна загрузиться на все воркеры сервиса.
WARMUP_CALLS = {"onnx": 5, "linq": 32}
FRAME_LIMIT = 100
ACCELERATOR_FRAMES = 30
LINQ_DEVICE = "LinQ TPU, 1 плата, через ретранслятор и сервис RabbitMQ"
ACCELERATOR_DEVICE = ("LinQ TPU, 1 плата, только время ускорителя "
                      "(без пре- и постпроцессинга, сети и очереди сервиса)")
PRECISION = {"onnx": "fp32", "linq": "int8"}


def load_frames(folder: Path) -> list[np.ndarray]:
    paths = sorted(folder.glob("*.jpg"))[:FRAME_LIMIT]
    return [cv2.imread(str(path)) for path in paths]


def measure(detector: Detector, frames: list[np.ndarray], streams: int, warmup_calls: int,
            seconds: float) -> tuple[float, dict[str, float]]:
    """fps и среднее время на кадр в мс; кадры раздаются потокам по кругу."""
    def batch(call: int) -> list[np.ndarray]:
        return [frames[(call * streams + k) % len(frames)] for k in range(streams)]

    for call in range(warmup_calls):
        detector.infer(batch(call))
    totals = {"pre": 0.0, "infer": 0.0, "post": 0.0}
    processed, call = 0, warmup_calls
    started = time.perf_counter()
    while time.perf_counter() - started < seconds:
        detector.infer(batch(call))
        for key in totals:
            totals[key] += detector.last_timing[key]
        processed += streams
        call += 1
    fps = processed / (time.perf_counter() - started)
    latency = {key: value / processed for key, value in totals.items()}
    return fps, latency | {"total": 1000 / fps}


def accelerator_ms(frames: list[np.ndarray]) -> float:
    """Среднее время расчёта на TPU за кадр, pose + det, по inference_time воркера, мс."""
    import ml.backends.linq as linq_backend

    worker_ms: list[float] = []
    original = linq_backend.deserialize

    # LinqDetector не отдаёт inference_time воркера, поэтому он читается из ответа здесь.
    def deserialize_with_timing(body: bytes) -> tuple:
        data, metadata, worker = original(body)
        worker_ms.append(worker["inference_time"] * 1000)
        return data, metadata, worker

    models_cfg = yaml.safe_load((ROOT / "configs/models.yaml").read_text())["models"]
    detector = linq_backend.LinqDetector(models_cfg, ROOT)
    linq_backend.deserialize = deserialize_with_timing
    try:
        per_frame = []
        for frame in frames[:ACCELERATOR_FRAMES]:
            worker_ms.clear()
            detector.infer([frame])
            per_frame.append(sum(worker_ms))
    finally:
        linq_backend.deserialize = original
    return statistics.mean(per_frame)


def record(backend: str, device: str, streams: int, fps: float,
           latency: dict[str, float]) -> dict:
    return {
        "model": MODEL,
        "backend": backend,
        "device": device,
        "precision": PRECISION[backend],
        "input": INPUT_SIZE,
        "streams": streams,
        "fps": round(fps, 3),
        "latency_ms": {key: round(latency[key], 1) for key in ("pre", "infer", "post", "total")},
        "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=Path, default=ROOT / "data/videos/calib")
    parser.add_argument("--backends", nargs="+", default=["onnx", "linq"])
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--out", type=Path, default=ROOT / "reports/benchmarks.json")
    args = parser.parse_args()

    frames = load_frames(args.frames)
    cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                         capture_output=True, text=True, check=True).stdout.strip()
    devices = {"onnx": f"CPU {cpu}", "linq": LINQ_DEVICE}
    records = []
    for backend in args.backends:
        detector = create_detector(backend)
        for streams in STREAMS[backend]:
            fps, latency = measure(detector, frames, streams, WARMUP_CALLS[backend], args.seconds)
            records.append(record(backend, devices[backend], streams, fps, latency))
            print(f"{backend} streams={streams}: fps {fps:.3f}, "
                  f"total {latency['total']:.1f} мс", flush=True)
    if "linq" in args.backends:
        tpu_ms = accelerator_ms(frames)
        records.append(record("linq", ACCELERATOR_DEVICE, 1, 1000 / tpu_ms,
                              {"pre": 0.0, "infer": tpu_ms, "post": 0.0, "total": tpu_ms}))
        print(f"linq только ускоритель: {tpu_ms:.2f} мс на кадр", flush=True)

    args.out.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    print(f"записей: {len(records)}, файл: {args.out}")


if __name__ == "__main__":
    main()
