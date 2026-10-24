"""Проверка правил fall и danger_zone: синтетика и data/demo.mp4. python scripts/check_rules.py."""
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from backend.cameras import load_cameras  # noqa: E402
from core.schemas import CameraConfig, Detection, RuleConfig, Zone  # noqa: E402
from logic import Engine, describe  # noqa: E402

W, H = 1280, 720
DT = 0.1
ZONE = Zone(id="z1", name="Zone 1", polygon=[(0.5, 0.5), (1.0, 0.5), (1.0, 1.0), (0.5, 1.0)])

failed = False


def check(name: str, fn) -> None:
    global failed
    try:
        fn()
        print(f"ok {name}")
    except Exception as e:
        failed = True
        print(f"fail {name}: {e!r}")


def expect(cond: bool, reason: str) -> None:
    if not cond:
        raise AssertionError(reason)


def _kpts(points: dict[int, tuple[float, float]]) -> np.ndarray:
    kpts = np.zeros((17, 3), dtype=np.float32)
    for i, (x, y) in points.items():
        kpts[i] = (x, y, 0.9)
    return kpts


def standing(fx: float, fy: float) -> Detection:
    """Стоящий человек 80x240, точка ног (fx, fy)."""
    x1, y1 = fx - 40, fy - 240
    kpts = _kpts({5: (fx - 15, y1 + 50), 6: (fx + 15, y1 + 50), 11: (fx - 12, y1 + 130), 12: (fx + 12, y1 + 130)})
    return Detection(cls="person", conf=0.9, bbox=(x1, y1, fx + 40, fy), kpts=kpts)


def lying(fx: float, fy: float, with_kpts: bool = True) -> Detection:
    """Лежащий человек 240x80, точка ног (fx, fy)."""
    x1, y1 = fx - 120, fy - 80
    cy = y1 + 40
    kpts = _kpts({5: (x1 + 60, cy - 8), 6: (x1 + 60, cy + 8), 11: (x1 + 140, cy - 8), 12: (x1 + 140, cy + 8)})
    return Detection(cls="person", conf=0.9, bbox=(x1, y1, fx + 120, fy), kpts=kpts if with_kpts else None)


def camera(rules=None, zones=None) -> CameraConfig:
    rules = rules or [RuleConfig(type="danger_zone", zone="z1"), RuleConfig(type="fall")]
    return CameraConfig(id="test", name="test", source="", fps=10, zones=zones or [ZONE], rules=rules)


class Run:
    def __init__(self, rules=None, zones=None):
        self.engine = Engine(camera(rules, zones))
        self.ts = 0.0
        self.events = []

    def frames(self, seconds: float, make):
        for i in range(round(seconds / DT)):
            result = self.engine.process(self.ts, W, H, make(i))
            self.events += result.new_events
            self.ts = round(self.ts + DT, 6)
        return self

    def of(self, rule_type: str):
        return [e for e in self.events if e.type == rule_type]


def dz_inside():
    run = Run().frames(2.0, lambda i: [standing(900, 600)])
    events = run.of("danger_zone")
    expect(len(events) == 1, f"{len(events)} events")
    expect(events[0].zone_id == "z1" and events[0].extra.get("zone_name"), f"{events[0].zone_id} {events[0].extra}")


def dz_outside():
    run = Run().frames(3.0, lambda i: [standing(300, 600)])
    expect(len(run.of("danger_zone")) == 0, f"{len(run.of('danger_zone'))} events")


def dz_feet_rule():
    # Правая верхняя часть бокса в зоне (x > 640, y > 360), точка ног (630, 700) левее зоны.
    det = Detection(cls="person", conf=0.9, bbox=(560.0, 380.0, 700.0, 700.0), kpts=None)
    run = Run().frames(3.0, lambda i: [det])
    expect(len(run.of("danger_zone")) == 0, f"{len(run.of('danger_zone'))} events")


def fall_standing():
    run = Run().frames(6.0, lambda i: [standing(300, 600)])
    expect(len(run.of("fall")) == 0, f"{len(run.of('fall'))} events")


def fall_lying():
    run = Run().frames(6.0, lambda i: [lying(300, 600)])
    events = run.of("fall")
    expect(len(events) == 1, f"{len(events)} events")
    e = events[0]
    d = e.ts_confirm - e.ts_start
    expect(e.severity == "critical" and e.extra.get("pose") == "kpts", f"{e.severity} {e.extra}")
    expect(1.5 - 1e-6 <= d <= 1.8 + 1e-6, f"ts_confirm - ts_start = {d:.2f}")


def fall_crawl():
    run = Run().frames(6.0, lambda i: [lying(150 + 15 * i, 600)])
    expect(len(run.of("fall")) == 0, f"{len(run.of('fall'))} events")


def fall_bbox():
    run = Run().frames(6.0, lambda i: [lying(300, 600, with_kpts=False)])
    events = run.of("fall")
    expect(len(events) == 1, f"{len(events)} events")
    expect(events[0].extra.get("pose") == "bbox", f"extra {events[0].extra}")


def fall_bend():
    run = Run().frames(2.0, lambda i: [standing(300, 600)]).frames(1.0, lambda i: [lying(300, 600)]) \
        .frames(3.0, lambda i: [standing(300, 600)])
    expect(len(run.of("fall")) == 0, f"{len(run.of('fall'))} events")


def registry():
    specs = {r["type"]: r for r in describe()}
    for t in ("fall", "danger_zone"):
        expect(t in specs, f"{t} missing")
        expect(set(specs[t]) == {"type", "title", "severity", "needs_zone", "params"}, f"{t} keys {sorted(specs[t])}")
        expect(any(p["name"] == "min_duration" for p in specs[t]["params"]), f"{t} no min_duration")


def broken_rule():
    rules = [RuleConfig(type="danger_zone", zone="z1", schedule=("25:00", "06:00")), RuleConfig(type="fall")]
    run = Run(rules).frames(6.0, lambda i: [lying(300, 600)])
    expect(len(run.of("fall")) == 1, f"{len(run.of('fall'))} fall events")


def demo_fall():
    events = demo_events("cam1")
    falls = [e for e in events if e.type == "fall"]
    expect(len(falls) == 1, f"{len(falls)} fall events")
    expect(falls[0].ts_start >= 3.0, f"ts_start {falls[0].ts_start}")


def demo_no_running():
    events = demo_events("cam2")
    running = [e for e in events if e.type == "running"]
    falls = [e for e in events if e.type == "fall"]
    expect(not running and len(falls) == 1, f"running {len(running)}, fall {len(falls)}")


_detector = []


def demo_events(camera_id: str):
    """data/demo.mp4 через детектор и Engine камеры без schedule, 10 кадров/с. Печатает события."""
    import cv2
    from ml import create_detector

    if not _detector:
        _detector.append(create_detector("onnx"))
    detector = _detector[0]
    cam = next(c for c in load_cameras() if c.id == camera_id)
    cam = dataclasses.replace(cam, rules=[dataclasses.replace(r, schedule=None) for r in cam.rules])
    engine = Engine(cam)
    cap = cv2.VideoCapture(str(ROOT / "data" / "demo.mp4"))
    step = (cap.get(cv2.CAP_PROP_FPS) or 25.0) / 10.0
    events, index, n, next_pos = [], 0, 0, 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index >= next_pos:
            ts = n / 10
            h, w = frame.shape[:2]
            result = engine.process(ts, w, h, detector.infer([frame])[0])
            events += result.new_events
            n += 1
            next_pos += step
        index += 1
    cap.release()
    # Пустые кадры после конца видео закрывают открытые события и задают ts_end
    for i in range(round(3.0 / DT)):
        engine.process(n / 10 + i * DT, w, h, [])
    for e in events:
        print(json.dumps({"camera_id": camera_id, "type": e.type, "track_id": e.track_id,
                          "ts_start": round(e.ts_start, 2), "ts_confirm": round(e.ts_confirm, 2),
                          "ts_end": round(e.ts_end, 2) if e.ts_end is not None else None,
                          "extra": e.extra}, ensure_ascii=False))
    return events


def forklift_video():
    """Первое видео с forklift в имени из data/videos/ через run_offline с proximity. Только печать."""
    videos = sorted(p for p in (ROOT / "data" / "videos").rglob("*") if "forklift" in p.name.lower()) \
        if (ROOT / "data" / "videos").exists() else []
    if not videos:
        print("forklift video: нет файлов в data/videos/")
        return
    import tempfile
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_offline import run_offline
    out = Path(tempfile.mkdtemp()) / "forklift.jsonl"
    events, frames, seconds = run_offline(str(videos[0]), "cam1", str(out), detector=_detector[0] if _detector else None)
    print(f"forklift video {videos[0].name}: {frames} frames, {seconds:.1f} s")
    for e in events:
        if e.type == "proximity":
            print(json.dumps({"type": e.type, "track_id": e.track_id, "ts_start": round(e.ts_start, 2),
                              "ts_confirm": round(e.ts_confirm, 2), "extra": e.extra}, ensure_ascii=False))


# Proximity и running: человек 80x200, грузовик 300x200
TRUCK = (600.0, 300.0, 900.0, 500.0)


def person(fx: float, fy: float) -> Detection:
    return Detection(cls="person", conf=0.9, bbox=(fx - 40, fy - 200, fx + 40, fy))


def truck(bbox=TRUCK) -> Detection:
    return Detection(cls="truck", conf=0.9, bbox=bbox)


def prox_run(seconds: float, make) -> Run:
    return Run([RuleConfig(type="proximity")]).frames(seconds, make)


def prox_near():
    events = prox_run(2.0, lambda i: [person(500, 500), truck()]).of("proximity")
    expect(len(events) == 1, f"{len(events)} events")
    expect(events[0].extra.get("vehicle") == "truck", f"extra {events[0].extra}")


def prox_far():
    run = prox_run(3.0, lambda i: [person(0, 500), truck()])
    # Точка ног (0, 500) на 600 px левее грузовика, 3 роста
    expect(len(run.of("proximity")) == 0, f"{len(run.of('proximity'))} events")


def prox_none():
    run = prox_run(3.0, lambda i: [person(500, 500)])
    expect(len(run.of("proximity")) == 0, f"{len(run.of('proximity'))} events")


def prox_two():
    second = (100.0, 300.0, 400.0, 500.0)
    run = prox_run(2.0, lambda i: [person(500, 500), truck(), truck(second)])
    expect(len(run.of("proximity")) == 1, f"{len(run.of('proximity'))} events")


def run_rule(seconds: float, make, zones=None, zone=None) -> Run:
    return Run([RuleConfig(type="running", zone=zone)], zones).frames(seconds, make)


def run_fast():
    run = run_rule(3.0, lambda i: [person(60 + 40 * i, 500)])
    expect(len(run.of("running")) == 1, f"{len(run.of('running'))} events")


def run_walk():
    run = run_rule(5.0, lambda i: [person(100 + 15 * i, 500)])
    expect(len(run.of("running")) == 0, f"{len(run.of('running'))} events")


def run_jitter():
    run = run_rule(5.0, lambda i: [person(500 + (20 if i % 2 else -20), 500)])
    expect(len(run.of("running")) == 0, f"{len(run.of('running'))} events")


def run_zone():
    # Зона в нижней половине кадра от x = 320: 960 px хватает на 2.4 с бега
    zone = Zone(id="floor", name="Floor", polygon=[(0.25, 0.5), (1.0, 0.5), (1.0, 1.0), (0.25, 1.0)])
    outside = run_rule(3.0, lambda i: [person(60 + 40 * i, 300)], zones=[zone], zone="floor")
    expect(len(outside.of("running")) == 0, f"outside {len(outside.of('running'))} events")
    inside = run_rule(3.0, lambda i: [person(340 + 40 * i, 650)], zones=[zone], zone="floor")
    expect(len(inside.of("running")) == 1, f"inside {len(inside.of('running'))} events")


def body(fx: float, fy: float, w: float, h: float, lying_t: float = 0.0) -> Detection:
    """Человек с боксом w x h, точка ног (fx, fy). Плечи над бёдрами при lying_t = 0,
    на одной высоте при lying_t = 1 (линейный переход)."""
    x1, y1 = fx - w / 2, fy - h
    cx, cy = fx, fy - h / 2
    half = 0.2 * max(w, h)
    # Вектор плечи -> бёдра поворачивается от вертикали к горизонтали
    dx, dy = half * lying_t, half * (1 - lying_t)
    kpts = _kpts({5: (cx - dx - 8, cy - dy), 6: (cx - dx + 8, cy - dy),
                  11: (cx + dx - 8, cy + dy), 12: (cx + dx + 8, cy + dy)})
    return Detection(cls="person", conf=0.9, bbox=(x1, y1, fx + w / 2, fy), kpts=kpts)


def run_depth():
    # Бег к камере: точка ног на месте, высота растёт со 150 до 300 px за 1 с и дальше в том же темпе
    run = run_rule(3.0, lambda i: [body(640, 700, 60 + 6 * i, 150 + 15 * i)])
    expect(len(run.of("running")) == 1, f"{len(run.of('running'))} events")


def run_depth_fall():
    # Стоит 1.5 с, за 1.2 с (12 кадров) плавно падает: высота 300 -> 100, ширина 100 -> 300,
    # корпус почти ложится (0.95 горизонтали, ~87 град), лежит 2 с.
    def make(i):
        if i < 15:
            return [body(640, 600, 100, 300)]
        p = min((i - 15) / 12, 1.0)
        return [body(640, 600, 100 + 200 * p, 300 - 200 * p, lying_t=0.95 * p)]

    def run(params=None):
        r = Run([RuleConfig(type="running", params=params or {})])
        ids = set()
        for i in range(round(4.7 / DT)):
            result = r.engine.process(r.ts, W, H, make(i))
            r.events += result.new_events
            if 15 <= i <= 27:
                ids.update(t.track_id for t in result.tracks)
            r.ts = round(r.ts + DT, 6)
        return r, ids

    checked, ids = run()
    expect(len(ids) == 1, f"track ids during fall {sorted(ids)}")
    expect(len(checked.of("running")) == 0, f"{len(checked.of('running'))} events")
    # Контроль: без проверки стойки то же падение даёт running, значит проверка стойки нагружена
    control, _ = run({"upright_angle": 90.0, "upright_aspect": 0.0})
    expect(len(control.of("running")) >= 1, f"control without upright check: {len(control.of('running'))} events")


def registry4():
    types = sorted(r["type"] for r in describe())
    expect(types == ["danger_zone", "fall", "proximity", "running"], f"{types}")


if __name__ == "__main__":
    check("dz_inside", dz_inside)
    check("dz_outside", dz_outside)
    check("dz_feet_rule", dz_feet_rule)
    check("fall_standing", fall_standing)
    check("fall_lying", fall_lying)
    check("fall_crawl", fall_crawl)
    check("fall_bbox", fall_bbox)
    check("fall_bend", fall_bend)
    check("registry", registry)
    check("broken_rule", broken_rule)
    check("prox_near", prox_near)
    check("prox_far", prox_far)
    check("prox_none", prox_none)
    check("prox_two", prox_two)
    check("run_fast", run_fast)
    check("run_walk", run_walk)
    check("run_jitter", run_jitter)
    check("run_zone", run_zone)
    check("run_depth", run_depth)
    check("run_depth_fall", run_depth_fall)
    check("registry4", registry4)
    check("demo_fall", demo_fall)
    check("demo_no_running", demo_no_running)
    forklift_video()
    sys.exit(1 if failed else 0)
