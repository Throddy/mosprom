"""Проверка пайплайна без сервера: python scripts/check_pipeline.py."""
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from backend.cameras import load_cameras  # noqa: E402
from backend.draw import draw  # noqa: E402
from backend.pipeline import Pipeline  # noqa: E402
from ml import create_detector  # noqa: E402

DURATION = 15.0
OUT = ROOT / "backend" / "media" / "check_pipeline.jpg"


def main() -> int:
    cameras = load_cameras()
    detector = create_detector("onnx")
    frames = Counter()
    with_person = Counter()

    def on_result(camera_id, ts, frame, detections):
        frames[camera_id] += 1
        if any(d.cls == "person" for d in detections):
            with_person[camera_id] += 1

    pipeline = Pipeline(cameras, detector, on_result)
    pipeline.start()
    time.sleep(DURATION)
    snaps = {c.id: pipeline.snapshot(c.id) for c in cameras}
    pipeline.stop()

    failed = False
    for cam in cameras:
        snap = snaps[cam.id]
        row = {
            "camera_id": cam.id,
            "online": snap["online"],
            "fps": round(snap["fps"], 1),
            "latency_ms": round(snap["latency_ms"], 1),
            "frames": frames[cam.id],
            "frames_with_person": with_person[cam.id],
        }
        print(json.dumps(row))
        if not snap["online"] or snap["fps"] < 3 or snap["latency_ms"] > 1000 or with_person[cam.id] == 0:
            failed = True

    cam1 = next(c for c in cameras if c.id == "cam1")
    snap = snaps["cam1"]
    if snap["frame"] is not None:
        info = f"cam1 fps {snap['fps']:.1f} lat {snap['latency_ms']:.0f} ms"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(OUT), draw(snap["frame"], snap["detections"], cam1.zones, info))
    else:
        failed = True

    if pipeline.detector_thread is not None and pipeline.detector_thread.is_alive():
        print("detector thread still alive after stop()")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
