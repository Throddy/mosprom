"""Проверка пайплайна без сервера: python scripts/check_pipeline.py.

С TILED_CAMERAS=cam2 основной прогон проверяет, что cam2 обрабатывается обработчиком с плитками.
Распределение камер и переход без плиток проверяются на фабрике-заглушке, без обращения к LinQ.
"""
import json
import os
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


class StubDetector:
    name = "stub"

    def infer(self, frames):
        return [[] for _ in frames]


def stub_factory(tiles_supported: bool, calls: list):
    def factory(backend=None, tiles=None):
        calls.append(tiles)
        if tiles and not tiles_supported:
            raise ValueError(f"{backend}: плитки не поддерживаются")
        return StubDetector()
    return factory


def run_stub(tiled: str, tiles_supported: bool, workers: str = "1") -> tuple[list[dict], dict, list, bool]:
    """Пайплайн на заглушке: обработчики, кадров по камерам за 2 с, вызовы фабрики, все потоки остановлены."""
    old = {k: os.environ.get(k) for k in ("TILED_CAMERAS", "TILED_WORKERS", "DETECTOR_WORKERS")}
    os.environ.update(TILED_CAMERAS=tiled, TILED_WORKERS=workers, DETECTOR_WORKERS="1")
    calls: list = []
    try:
        pipeline = Pipeline(load_cameras(), StubDetector(), factory=stub_factory(tiles_supported, calls))
        pipeline.start()
        time.sleep(2.0)
        processed = {cid: len(cam.processed) for cid, cam in pipeline.cams.items()}
        pipeline.stop()
        stopped = not any(t.is_alive() for t in pipeline.detector_threads)
        return pipeline.workers, processed, calls, stopped
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def check_distribution() -> bool:
    failed = False
    cases = [
        ("mixed", "cam2, cam2 ,unknown", True, [(False, ["cam1"]), (True, ["cam2"])], [True]),
        ("empty", "", True, [(False, ["cam1", "cam2"])], []),
        ("all_tiled", "cam1,cam2", True, [(True, ["cam1", "cam2"])], [True]),
        ("no_tiles_backend", "cam2", False, [(False, ["cam1", "cam2"])], [True]),
    ]
    for name, tiled, supported, expected, tiled_calls in cases:
        workers, processed, calls, stopped = run_stub(tiled, supported)
        got = [(w["tiles"], w["cameras"]) for w in workers]
        ok = (got == expected and all(n > 0 for n in processed.values()) and stopped
              and [c for c in calls if c] == tiled_calls)
        print(json.dumps({"check": f"workers_{name}", "ok": ok, "workers": got, "processed": processed,
                          "tiles_calls": calls.count(True), "stopped": stopped}, ensure_ascii=False))
        failed |= not ok
    # TILED_WORKERS больше числа камер группы: обработчиков не больше, чем камер
    workers, _, _, stopped = run_stub("cam1,cam2", True, workers="5")
    ok = [w["cameras"] for w in workers] == [["cam1"], ["cam2"]] and stopped
    print(json.dumps({"check": "workers_tiled_limit", "ok": ok, "workers": [w["cameras"] for w in workers]}))
    failed |= not ok
    return failed


def check_hls_source() -> bool:
    """HlsSource на локальном HLS из 3 с data/demo.mp4: размер из RESOLUTION, темп -re, переподключение
    после конца потока, остановка завершает ffmpeg и поток чтения. Публичные трансляции не нужны."""
    import subprocess
    import tempfile

    from backend.sources import HlsSource
    tmp = Path(tempfile.mkdtemp(prefix="check_hls_"))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(ROOT / "data" / "demo.mp4"), "-t", "3",
                    "-an", "-vf", "scale=640:360", "-c:v", "libx264", "-g", "10", "-hls_time", "1",
                    "-hls_list_size", "0", str(tmp / "v.m3u8")], check=True)
    (tmp / "master.m3u8").write_text("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=500000,RESOLUTION=640x360\nv.m3u8\n")
    src = HlsSource((tmp / "master.m3u8").as_uri(), 10)
    src.reconnect = 0.5
    stamps, shapes, procs = [], set(), set()
    end = time.time() + 9.0
    while time.time() < end:
        item = src.read()
        if item is None:
            break
        stamps.append(item[0])
        shapes.add(item[1].shape)
        procs.add(id(getattr(src, "proc", None)))
    proc = src.proc
    t = time.time()
    src.close()
    closed_s = time.time() - t
    first = [x for x in stamps if x <= stamps[0] + 2.5] if stamps else []
    ok = (shapes == {(360, 640, 3)} and 12 <= len(first) <= 32 and len(procs) >= 2
          and proc.poll() is not None and not src.thread.is_alive() and closed_s < 3.5)
    print(json.dumps({"check": "hls_source", "ok": ok, "frames": len(stamps), "frames_first_2_5s": len(first),
                      "shapes": sorted(shapes), "ffmpeg_runs": len(procs), "close_s": round(closed_s, 2),
                      "ffmpeg_exited": proc.poll() is not None, "thread_alive": src.thread.is_alive()}))
    return not ok


def main() -> int:
    cameras = load_cameras()
    detector = create_detector("onnx")
    tiles_calls: list = []

    def factory(backend=None, tiles=None):
        tiles_calls.append(tiles)
        return create_detector(backend, tiles=tiles)
    frames = Counter()
    with_person = Counter()

    def on_result(camera_id, ts, frame, result):
        frames[camera_id] += 1
        if any(t.cls == "person" for t in result.tracks):
            with_person[camera_id] += 1

    pipeline = Pipeline(cameras, detector, on_result, factory=factory)
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
        cv2.imwrite(str(OUT), draw(snap["frame"], snap["detections"], cam1.zones, info, snap["tracks"]))
    else:
        failed = True

    if pipeline.detector_thread is not None and pipeline.detector_thread.is_alive():
        print("detector thread still alive after stop()")
        failed = True

    tiled = [w for w in pipeline.workers if w["tiles"]]
    print(json.dumps({"workers": [(w["name"], w["cameras"]) for w in pipeline.workers],
                      "factory_tiles_calls": tiles_calls.count(True)}))
    if os.environ.get("TILED_CAMERAS", "").strip() == "cam2":
        if [w["cameras"] for w in tiled] != [["cam2"]] or tiles_calls.count(True) != 1 or frames["cam2"] == 0:
            print("cam2 is not processed by a tiled worker")
            failed = True

    failed |= check_distribution()
    failed |= check_hls_source()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
