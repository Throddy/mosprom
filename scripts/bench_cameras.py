"""Замер нескольких камер на onnx: FPS, задержка обработки, задержка до event_new, загрузка CPU.

python scripts/bench_cameras.py [--counts 1,2,4,6] [--fps 10] [--seconds 30] [--source data/demo.mp4]
"""
import argparse
import json
import os
import platform
import resource
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from backend.db import EventDB  # noqa: E402
from backend.pipeline import Pipeline  # noqa: E402
from core.schemas import CameraConfig, RuleConfig  # noqa: E402

WARMUP = 5.0
OUT = ROOT / "backend" / "data" / "bench_cameras.json"


def pct(values: list[float], q: float) -> float | None:
    return round(float(np.percentile(values, q)), 1) if values else None


class Collector:
    """Обработчик on_result: задержка кадра и задержка до event_new, как в backend/app.py."""

    def __init__(self):
        self.lock = threading.Lock()
        self.active = False
        self.db = EventDB(":memory:")
        self.frames: dict[str, list[float]] = {}
        self.alarms: dict[str, list[float]] = {}

    def start(self, camera_ids: list[str]) -> None:
        with self.lock:
            self.frames = {c: [] for c in camera_ids}
            self.alarms = {c: [] for c in camera_ids}
            self.active = True

    def stop(self) -> None:
        with self.lock:
            self.active = False

    def __call__(self, camera_id, ts, frame, result):
        # Сохранение в базу, как при отправке event_new на сервере; время до передачи в WebSocket
        for event in result.new_events:
            self.db.insert(event, f"{camera_id}/{event.id}.jpg")
        now = time.time()
        with self.lock:
            if not self.active:
                return
            self.frames[camera_id].append((getattr(result, "t_done", now) - ts) * 1000.0)
            for _ in result.new_events:
                self.alarms[camera_id].append((now - ts) * 1000.0)


def bench(n: int, fps: float, seconds: float, source: str, detector) -> dict:
    cameras = [CameraConfig(id=f"bench{i}", name=f"bench{i}", source=source, fps=fps,
                            rules=[RuleConfig(type="fall"), RuleConfig(type="running")])
               for i in range(1, n + 1)]
    collector = Collector()
    pipeline = Pipeline(cameras, detector, collector)
    pipeline.start()
    time.sleep(WARMUP)
    usage0 = resource.getrusage(resource.RUSAGE_SELF)
    collector.start([c.id for c in cameras])
    t0 = time.time()
    time.sleep(seconds)
    collector.stop()
    elapsed = time.time() - t0
    usage1 = resource.getrusage(resource.RUSAGE_SELF)
    load = os.getloadavg()[0]
    pipeline.stop()

    per_camera = {}
    for cam_id, lat in collector.frames.items():
        alarms = collector.alarms[cam_id]
        per_camera[cam_id] = {
            "fps": round(len(lat) / elapsed, 2),
            "latency_ms_p50": pct(lat, 50), "latency_ms_p95": pct(lat, 95),
            "events": len(alarms),
            "frame_to_ws_ms_p50": pct(alarms, 50), "frame_to_ws_ms_p95": pct(alarms, 95),
        }
    cpu = (usage1.ru_utime - usage0.ru_utime) + (usage1.ru_stime - usage0.ru_stime)
    total_fps = sum(c["fps"] for c in per_camera.values())
    all_lat = [x for lat in collector.frames.values() for x in lat]
    all_alarms = [x for a in collector.alarms.values() for x in a]
    return {
        "cameras": n, "target_fps": fps, "seconds": round(elapsed, 1),
        "total_fps": round(total_fps, 2), "fps_per_camera": round(total_fps / n, 2),
        "latency_ms_p50": pct(all_lat, 50), "latency_ms_p95": pct(all_lat, 95),
        "events": len(all_alarms),
        "frame_to_ws_ms_p50": pct(all_alarms, 50), "frame_to_ws_ms_p95": pct(all_alarms, 95),
        "loadavg_1m": round(load, 2), "cpu_s_per_s": round(cpu / elapsed, 2),
        "per_camera": per_camera,
    }


def print_table(rows: list[dict]) -> None:
    head = ("N", "FPS всего", "FPS/камера", "lat p50", "lat p95", "событий", "to_ws p50", "to_ws p95",
            "load 1m", "CPU с/с")
    print(" | ".join(head))
    for r in rows:
        print(" | ".join(str(v) for v in (
            r["cameras"], r["total_fps"], r["fps_per_camera"], r["latency_ms_p50"], r["latency_ms_p95"],
            r["events"], r["frame_to_ws_ms_p50"], r["frame_to_ws_ms_p95"], r["loadavg_1m"], r["cpu_s_per_s"])))


def main() -> int:
    parser = argparse.ArgumentParser(description="Замер нескольких камер на onnx")
    parser.add_argument("--counts", default="1,2,4,6")
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--source", default="data/demo.mp4")
    args = parser.parse_args()
    counts = [int(x) for x in args.counts.split(",") if x.strip()]

    from ml import create_detector
    detector = create_detector("onnx")
    rows = []
    queue = list(counts)
    while queue:
        n = queue.pop(0)
        row = bench(n, args.fps, args.seconds, args.source, detector)
        rows.append(row)
        print(f"N={n}: FPS/камера {row['fps_per_camera']}, lat p95 {row['latency_ms_p95']} мс", flush=True)
        if n == 6:
            if row["fps_per_camera"] < 3:
                queue = [c for c in queue if c <= 6]
            elif row["fps_per_camera"] >= 0.9 * args.fps and 8 not in counts:
                queue.append(8)

    print()
    print(f"{platform.platform()}, процессор {platform.processor() or platform.machine()}, "
          f"цель {args.fps:g} кадров/с на камеру, {args.seconds:g} с сбора после {WARMUP:g} с прогрева")
    print_table(rows)
    ok = [r["cameras"] for r in rows if r["fps_per_camera"] >= 0.9 * args.fps]
    verdict = max(ok) if ok else 0
    print(f"Вывод: при {args.fps:g} кадрах/с на камеру машина тянет {verdict} камер "
          f"(FPS на камеру не ниже 90 % заданного)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[f"fps_{args.fps:g}"] = {
        "platform": platform.platform(), "processor": platform.processor() or platform.machine(),
        "max_cameras": verdict, "rows": rows,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
