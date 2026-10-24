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


def camera(rules=None) -> CameraConfig:
    rules = rules or [RuleConfig(type="danger_zone", zone="z1"), RuleConfig(type="fall")]
    return CameraConfig(id="test", name="test", source="", fps=10, zones=[ZONE], rules=rules)


class Run:
    def __init__(self, rules=None):
        self.engine = Engine(camera(rules))
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
    expect(3.0 - 1e-6 <= d <= 3.3 + 1e-6, f"ts_confirm - ts_start = {d:.2f}")


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
    import cv2
    from ml import create_detector

    cam = next(c for c in load_cameras() if c.id == "cam1")
    cam = dataclasses.replace(cam, rules=[dataclasses.replace(r, schedule=None) for r in cam.rules])
    engine = Engine(cam)
    detector = create_detector("onnx")
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
        print(json.dumps({"type": e.type, "track_id": e.track_id, "ts_start": round(e.ts_start, 2),
                          "ts_confirm": round(e.ts_confirm, 2),
                          "ts_end": round(e.ts_end, 2) if e.ts_end is not None else None,
                          "extra": e.extra}, ensure_ascii=False))
    falls = [e for e in events if e.type == "fall"]
    expect(len(falls) == 1, f"{len(falls)} fall events")
    expect(falls[0].ts_start >= 3.0, f"ts_start {falls[0].ts_start}")


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
    check("demo_fall", demo_fall)
    sys.exit(1 if failed else 0)
