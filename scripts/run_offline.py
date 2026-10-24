"""Прогон видео через детектор и правила без сервера (CONTRACT.md, раздел 7).

python scripts/run_offline.py --video PATH --camera ID --out PATH [--fps F] [--use-schedule]
"""
import argparse
import dataclasses
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from backend.cameras import load_cameras  # noqa: E402
from core.schemas import Event  # noqa: E402
from logic import Engine  # noqa: E402


class OfflineError(Exception):
    pass


def run_offline(video: str, camera_id: str, out: str, fps: float | None = None,
                use_schedule: bool = False, detector=None) -> tuple[list[Event], int, float]:
    """Возвращает события (ts_* в секундах от начала видео), число обработанных кадров и время работы."""
    cameras = {c.id: c for c in load_cameras()}
    if camera_id not in cameras:
        raise OfflineError(f"камера {camera_id} не найдена в configs/cameras.yaml")
    camera = cameras[camera_id]
    if not use_schedule:
        camera = dataclasses.replace(camera, rules=[dataclasses.replace(r, schedule=None) for r in camera.rules])
    fps = fps or camera.fps
    camera = dataclasses.replace(camera, fps=fps)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise OfflineError(f"видео не открывается: {video}")
    if detector is None:
        from ml import create_detector
        detector = create_detector()

    started = time.time()
    # С расписанием ts движка идёт от текущего времени, в вывод попадает время от начала видео
    offset = started if use_schedule else 0.0
    engine = Engine(camera)
    step = (cap.get(cv2.CAP_PROP_FPS) or 25.0) / fps
    events: list[Event] = []
    index, n, next_pos, ts = 0, 0, 0.0, 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index >= next_pos:
            ts = n / fps
            h, w = frame.shape[:2]
            result = engine.process(ts + offset, w, h, detector.infer([frame])[0])
            events += result.new_events
            n += 1
            next_pos += step
        index += 1
    cap.release()

    for event in events:
        if event.ts_end is None:
            event.ts_end = ts + offset
        if offset:
            event.ts_start -= offset
            event.ts_confirm -= offset
            event.ts_end -= offset
    events.sort(key=lambda e: e.ts_confirm)

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(dataclasses.asdict(event), ensure_ascii=False) + "\n")
    return events, n, time.time() - started


def main() -> int:
    parser = argparse.ArgumentParser(description="Прогон видео через детектор и правила без сервера")
    parser.add_argument("--video", required=True)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--fps", type=float, default=None, help="частота обработки, по умолчанию fps камеры")
    parser.add_argument("--use-schedule", action="store_true", help="учитывать schedule правил")
    args = parser.parse_args()
    try:
        events, frames, seconds = run_offline(args.video, args.camera, args.out, args.fps, args.use_schedule)
    except OfflineError as e:
        print(f"run_offline: {e}", file=sys.stderr)
        return 2
    counts = Counter(e.type for e in events)
    types = " ".join(f"{t}={c}" for t, c in sorted(counts.items())) or "-"
    print(f"{args.video}: {frames} frames, {len(events)} events, {types}, {seconds:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
