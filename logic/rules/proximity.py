"""Сближение человека с техникой: расстояние от точки ног до бокса техники в ростах человека."""
from core.schemas import RuleConfig
from logic.geometry import bbox_height, foot_point, point_in_polygon
from logic.rules.base import FrameContext, Rule

VEHICLES = ("car", "truck", "bus", "forklift")


def point_to_box(x: float, y: float, bbox) -> float:
    """Расстояние от точки до прямоугольника, 0 если точка внутри."""
    x1, y1, x2, y2 = bbox
    dx = max(x1 - x, 0.0, x - x2)
    dy = max(y1 - y, 0.0, y - y2)
    return (dx * dx + dy * dy) ** 0.5


class ProximityRule(Rule):
    type = "proximity"
    title = "Сближение с техникой"
    severity = "critical"
    needs_zone = False
    params = [
        {"name": "dist", "type": "float", "unit": "рост человека", "default": 1.0},
        {"name": "min_duration", "type": "float", "unit": "с", "default": 0.5},
    ]

    def check(self, ctx: FrameContext, cfg: RuleConfig) -> dict[int, dict]:
        limit = float(self.param(cfg, "dist"))
        zone = ctx.zones.get(cfg.zone) if cfg.zone else None
        vehicles = [t for t in ctx.tracks.values() if t.cls in VEHICLES]
        if not vehicles:
            return {}
        violators = {}
        for track in ctx.tracks.values():
            if track.cls != "person":
                continue
            h = bbox_height(track.bbox)
            if h <= 0:
                continue
            x, y = foot_point(track.bbox)
            if zone is not None and not point_in_polygon(x / ctx.width, y / ctx.height, zone.polygon):
                continue
            d_norm, nearest = min(((point_to_box(x, y, v.bbox) / h, v) for v in vehicles), key=lambda p: p[0])
            if d_norm < limit:
                violators[track.track_id] = {"vehicle": nearest.cls, "vehicle_track": nearest.track_id,
                                             "dist": round(d_norm, 2)}
        return violators
