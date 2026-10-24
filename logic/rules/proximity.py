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


def inside_share(inner, outer) -> float:
    """Доля площади бокса inner, которая лежит внутри бокса outer."""
    ix1, iy1, ix2, iy2 = inner
    ox1, oy1, ox2, oy2 = outer
    area = max(ix2 - ix1, 0.0) * max(iy2 - iy1, 0.0)
    if area <= 0:
        return 0.0
    w = max(min(ix2, ox2) - max(ix1, ox1), 0.0)
    h = max(min(iy2, oy2) - max(iy1, oy1), 0.0)
    return w * h / area


def is_inside(person_bbox, vehicle_bbox, inside_ratio: float) -> bool:
    """Человек в кабине или водитель: точка ног внутри бокса техники и не меньше inside_ratio
    площади бокса человека внутри бокса техники."""
    x, y = foot_point(person_bbox)
    return point_to_box(x, y, vehicle_bbox) == 0.0 and inside_share(person_bbox, vehicle_bbox) >= inside_ratio


class ProximityRule(Rule):
    type = "proximity"
    title = "Сближение с техникой"
    severity = "critical"
    needs_zone = False
    params = [
        {"name": "dist", "type": "float", "unit": "рост человека", "default": 1.0},
        {"name": "inside_ratio", "type": "float", "unit": "доля", "default": 0.7},
        {"name": "min_duration", "type": "float", "unit": "с", "default": 0.5},
    ]

    def check(self, ctx: FrameContext, cfg: RuleConfig) -> dict[int, dict]:
        limit = float(self.param(cfg, "dist"))
        inside_ratio = float(self.param(cfg, "inside_ratio"))
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
            # Технику, в кабине которой находится человек, для него не учитываем: это водитель
            nearby = [(point_to_box(x, y, v.bbox) / h, v) for v in vehicles
                      if not is_inside(track.bbox, v.bbox, inside_ratio)]
            if not nearby:
                continue
            d_norm, nearest = min(nearby, key=lambda p: p[0])
            if d_norm < limit:
                violators[track.track_id] = {"vehicle": nearest.cls, "vehicle_track": nearest.track_id,
                                             "dist": round(d_norm, 2)}
        return violators
