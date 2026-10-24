"""Проверка трекера и движка событий на синтетических детекциях: python scripts/check_logic.py."""
import sys
import time as _time
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schemas import CameraConfig, Detection, RuleConfig  # noqa: E402
from logic import Engine, describe, register  # noqa: E402
from logic.engine import in_schedule  # noqa: E402
from logic.rules.base import FrameContext, Rule  # noqa: E402

W, H = 1280, 720
DT = 0.1
LEFT_X, RIGHT_X = 300.0, 900.0


class RightHalf(Rule):
    type = "_test_right"
    title = "Test: right half"
    severity = "high"
    needs_zone = False
    params = [{"name": "min_duration", "type": "float", "unit": "с", "default": 1.0}]

    def check(self, ctx: FrameContext, cfg: RuleConfig) -> dict[int, dict]:
        return {t.track_id: {} for t in ctx.tracks.values() if (t.bbox[0] + t.bbox[2]) / 2 > ctx.width / 2}


register(RightHalf())

failed = False


def check(name: str, fn) -> None:
    global failed
    try:
        fn()
        print(f"ok {name}")
    except Exception as e:
        failed = True
        print(f"fail {name}: {e}")


def expect(cond: bool, reason: str) -> None:
    if not cond:
        raise AssertionError(reason)


def person(cx: float, cy: float = 400.0) -> Detection:
    return Detection(cls="person", conf=0.9, bbox=(cx - 40, cy - 120, cx + 40, cy + 120))


def camera(schedule=None) -> CameraConfig:
    return CameraConfig(id="test", name="test", source="", fps=10,
                        rules=[RuleConfig(type="_test_right", schedule=schedule)])


class Run:
    """Прогон кадров через Engine с шагом DT."""

    def __init__(self, schedule=None):
        self.engine = Engine(camera(schedule))
        self.ts = _time.time()
        self.new, self.closed, self.track_ids = [], [], []

    def frames(self, seconds: float, make):
        for _ in range(round(seconds / DT)):
            dets = make() if make else []
            result = self.engine.process(self.ts, W, H, dets)
            self.new += result.new_events
            for e in result.closed_events:
                self.closed.append((e, self.ts))
            self.track_ids.append([t.track_id for t in result.tracks])
            self.ts += DT
        return self


def track_stable():
    xs = iter(range(100, 100 + 5 * 60, 5))
    run = Run().frames(6.0, lambda: [person(next(xs))])
    ids = {tuple(i) for i in run.track_ids}
    expect(len(ids) == 1 and len(next(iter(ids))) == 1, f"track ids {sorted(ids)}")


def min_duration():
    run = Run().frames(0.8, lambda: [person(RIGHT_X)]).frames(2.0, lambda: [person(LEFT_X)])
    expect(len(run.new) == 0, f"{len(run.new)} events")


def one_event_run() -> Run:
    return Run().frames(5.0, lambda: [person(RIGHT_X)])


def one_event():
    run = one_event_run()
    expect(len(run.new) == 1, f"{len(run.new)} events")
    d = run.new[0].ts_confirm - run.new[0].ts_start
    expect(1.0 - 1e-6 <= d <= 1.2 + 1e-6, f"ts_confirm - ts_start = {d:.3f}")


def grace():
    run = Run().frames(1.5, lambda: [person(RIGHT_X)]).frames(0.5, None).frames(2.0, lambda: [person(RIGHT_X)])
    expect(len(run.new) == 1, f"{len(run.new)} events")


def close():
    run = one_event_run()
    xs = iter(range(int(RIGHT_X), 0, -60))
    run.frames(4.0, lambda: [person(max(next(xs, 100), 100))])
    expect(len(run.closed) == 1, f"{len(run.closed)} closed")
    event, ts = run.closed[0]
    expect(event.ts_end is not None and event.ts_end <= ts, f"ts_end {event.ts_end} ts {ts}")


def track_lost():
    run = Run().frames(3.0, lambda: [person(RIGHT_X)]).frames(3.0, None)
    expect(len(run.new) == 1, f"{len(run.new)} events")
    expect(len(run.closed) == 1 and run.closed[0][0].ts_end is not None, f"{len(run.closed)} closed")


def two_tracks():
    run = Run().frames(3.0, lambda: [person(750, 200), person(1150, 550)])
    ids = {e.track_id for e in run.new}
    expect(len(run.new) == 2 and len(ids) == 2, f"{len(run.new)} events, track ids {sorted(ids)}")


def schedule():
    now = datetime.now()
    start = (now + timedelta(hours=2)).strftime("%H:%M")
    end = (now + timedelta(hours=3)).strftime("%H:%M")
    run = Run(schedule=(start, end)).frames(3.0, lambda: [person(RIGHT_X)])
    expect(len(run.new) == 0, f"{len(run.new)} events with schedule {start}-{end}")


def schedule_midnight():
    s = ("22:00", "06:00")
    expect(in_schedule(s, time(23, 30)), "23:30 outside")
    expect(in_schedule(s, time(5, 59)), "05:59 outside")
    expect(not in_schedule(s, time(12, 0)), "12:00 inside")


def describe_rules():
    spec = next((r for r in describe() if r["type"] == "_test_right"), None)
    expect(spec is not None, "_test_right missing")
    expect(set(spec) == {"type", "title", "severity", "needs_zone", "params"}, f"keys {sorted(spec)}")
    expect(any(p["name"] == "min_duration" for p in spec["params"]), "no min_duration")


if __name__ == "__main__":
    check("track_stable", track_stable)
    check("min_duration", min_duration)
    check("one_event", one_event)
    check("grace", grace)
    check("close", close)
    check("track_lost", track_lost)
    check("two_tracks", two_tracks)
    check("schedule", schedule)
    check("schedule_midnight", schedule_midnight)
    check("describe", describe_rules)
    sys.exit(1 if failed else 0)
