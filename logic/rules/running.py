"""Бег: чистое смещение точки ног за окно в ростах человека в секунду."""
from statistics import median

from core.schemas import RuleConfig
from logic.geometry import bbox_height, foot_point, point_in_polygon
from logic.rules.base import FrameContext, Rule, TrackState


def speed(track: TrackState, ts: float, window: float) -> float | None:
    """Скорость в ростах человека в секунду или None, если история короче 0.8 окна."""
    points = [(t, bbox) for t, bbox, _ in track.history if t >= ts - window]
    if len(points) < 2:
        return None
    (t0, b0), (t1, b1) = points[0], points[-1]
    if t1 - t0 < 0.8 * window:
        return None
    h = median(bbox_height(b) for _, b in points)
    if h <= 0:
        return None
    (x0, y0), (x1, y1) = foot_point(b0), foot_point(b1)
    s = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    return s / h / (t1 - t0)


class RunningRule(Rule):
    type = "running"
    title = "Бег в зоне работы техники"
    severity = "high"
    needs_zone = False
    params = [
        {"name": "speed", "type": "float", "unit": "рост человека/с", "default": 1.5},
        {"name": "window", "type": "float", "unit": "с", "default": 1.0},
        {"name": "min_duration", "type": "float", "unit": "с", "default": 1.0},
    ]

    def check(self, ctx: FrameContext, cfg: RuleConfig) -> dict[int, dict]:
        limit = float(self.param(cfg, "speed"))
        window = float(self.param(cfg, "window"))
        zone = ctx.zones.get(cfg.zone) if cfg.zone else None
        violators = {}
        for track in ctx.tracks.values():
            if track.cls != "person":
                continue
            if zone is not None:
                x, y = foot_point(track.bbox)
                if not point_in_polygon(x / ctx.width, y / ctx.height, zone.polygon):
                    continue
            v = speed(track, ctx.ts, window)
            if v is not None and v > limit:
                violators[track.track_id] = {"speed": round(v, 2)}
        return violators
