"""Бег: смещение точки ног и, пока человек стоит прямо, изменение высоты бокса за окно в ростах человека в секунду."""
from math import atan2, degrees, log, sqrt
from statistics import median

import numpy as np

from core.schemas import RuleConfig
from logic.geometry import bbox_height, foot_point, point_in_polygon
from logic.rules.base import FrameContext, Rule, TrackState

SHOULDERS = (5, 6)
HIPS = (11, 12)
KPT_CONF = 0.5


def _mid(kpts: np.ndarray, idx: tuple[int, int]) -> np.ndarray | None:
    pts = [kpts[i, :2] for i in idx if kpts[i, 2] > KPT_CONF]
    return np.mean(pts, axis=0) if pts else None


def is_upright(record, upright_angle: float, upright_aspect: float) -> bool:
    """Запись истории (ts, bbox, kpts): человек стоит прямо.

    По точкам: угол корпуса (плечи — бёдра) от вертикали меньше upright_angle.
    Без точек: высота бокса к ширине больше upright_aspect.
    """
    _, bbox, kpts = record
    # Точки неверной формы считаются отсутствующими: решает признак по боксу, а не исключение
    if isinstance(kpts, np.ndarray) and kpts.shape == (17, 3):
        shoulders, hips = _mid(kpts, SHOULDERS), _mid(kpts, HIPS)
        if shoulders is not None and hips is not None:
            dx, dy = hips - shoulders
            return degrees(atan2(abs(dx), abs(dy))) < upright_angle
    x1, y1, x2, y2 = bbox
    w = x2 - x1
    return w > 0 and (y2 - y1) / w > upright_aspect


def speed(track: TrackState, ts: float, window: float, depth_k: float = 0.0, upright_angle: float = 30.0,
          upright_aspect: float = 1.5) -> float | None:
    """Итоговая скорость v в ростах человека в секунду или None, если история короче 0.8 окна."""
    parts = speed_parts(track, ts, window, depth_k, upright_angle, upright_aspect)
    return parts[0] if parts else None


def speed_parts(track: TrackState, ts: float, window: float, depth_k: float = 0.0, upright_angle: float = 30.0,
                upright_aspect: float = 1.5) -> tuple[float, float, float] | None:
    """(v, v_lat, v_depth) в ростах человека в секунду или None, если история короче 0.8 окна.

    v_lat — чистое смещение точки ног, делённое на медианную высоту бокса.
    v_depth — depth_k * |ln(h_last / h_first)| за секунду: при беге к камере или от неё точка ног
    смещается мало, а меняется высота бокса. Учитывается, только если человек стоит прямо во всех
    записях окна: при падении высота бокса тоже резко меняется.
    """
    records = [r for r in track.history if r[0] >= ts - window]
    if len(records) < 2:
        return None
    (t0, b0, _), (t1, b1, _) = records[0], records[-1]
    dt = t1 - t0
    if dt < 0.8 * window:
        return None
    h = median(bbox_height(r[1]) for r in records)
    if h <= 0:
        return None
    (x0, y0), (x1, y1) = foot_point(b0), foot_point(b1)
    v_lat = sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2) / h / dt
    v_depth = 0.0
    h0, h1 = bbox_height(b0), bbox_height(b1)
    if depth_k > 0 and h0 > 0 and h1 > 0 and all(is_upright(r, upright_angle, upright_aspect) for r in records):
        v_depth = depth_k * abs(log(h1 / h0)) / dt
    return sqrt(v_lat ** 2 + v_depth ** 2), v_lat, v_depth


class RunningRule(Rule):
    type = "running"
    title = "Бег в зоне работы техники"
    severity = "high"
    needs_zone = False
    params = [
        {"name": "speed", "type": "float", "unit": "рост человека/с", "default": 1.5},
        {"name": "window", "type": "float", "unit": "с", "default": 1.0},
        {"name": "depth_k", "type": "float", "unit": "коэфф.", "default": 5.0},
        {"name": "upright_angle", "type": "float", "unit": "град", "default": 30.0},
        {"name": "upright_aspect", "type": "float", "unit": "высота/ширина", "default": 1.5},
        {"name": "min_duration", "type": "float", "unit": "с", "default": 1.0},
    ]

    def check(self, ctx: FrameContext, cfg: RuleConfig) -> dict[int, dict]:
        limit = float(self.param(cfg, "speed"))
        window = float(self.param(cfg, "window"))
        depth_k = float(self.param(cfg, "depth_k"))
        upright_angle = float(self.param(cfg, "upright_angle"))
        upright_aspect = float(self.param(cfg, "upright_aspect"))
        zone = ctx.zones.get(cfg.zone) if cfg.zone else None
        violators = {}
        for track in ctx.tracks.values():
            if track.cls != "person":
                continue
            if zone is not None:
                x, y = foot_point(track.bbox)
                if not point_in_polygon(x / ctx.width, y / ctx.height, zone.polygon):
                    continue
            result = speed_parts(track, ctx.ts, window, depth_k, upright_angle, upright_aspect)
            if result is None:
                continue
            v, v_lat, v_depth = result
            if v > limit:
                violators[track.track_id] = {"speed": round(v, 2), "lateral": round(v_lat, 2),
                                             "depth": round(v_depth, 2)}
        return violators
