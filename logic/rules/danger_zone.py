"""Человек в опасной зоне: точка ног внутри полигона зоны."""
from core.schemas import RuleConfig
from logic.geometry import foot_point, point_in_polygon
from logic.rules.base import FrameContext, Rule


class DangerZoneRule(Rule):
    type = "danger_zone"
    title = "Человек в опасной зоне"
    severity = "high"
    needs_zone = True
    params = [{"name": "min_duration", "type": "float", "unit": "с", "default": 1.0}]

    def check(self, ctx: FrameContext, cfg: RuleConfig) -> dict[int, dict]:
        zone = ctx.zones[cfg.zone]
        violators = {}
        for track in ctx.tracks.values():
            if track.cls != "person":
                continue
            x, y = foot_point(track.bbox)
            if point_in_polygon(x / ctx.width, y / ctx.height, zone.polygon):
                violators[track.track_id] = {"zone_name": zone.name}
        return violators
