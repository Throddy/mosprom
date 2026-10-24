"""Падение и неподвижность: корпус близок к горизонтали и человек не двигается."""
from math import atan2, degrees

import numpy as np

from core.schemas import RuleConfig
from logic.rules.base import FrameContext, Rule, TrackState

SHOULDERS = (5, 6)
HIPS = (11, 12)
KPT_CONF = 0.5


def _mid(kpts: np.ndarray, idx: tuple[int, int]) -> np.ndarray | None:
    pts = [kpts[i, :2] for i in idx if kpts[i, 2] > KPT_CONF]
    return np.mean(pts, axis=0) if pts else None


def is_lying(track: TrackState, angle: float, aspect: float) -> tuple[bool, str, float | None]:
    if track.kpts is not None:
        shoulders = _mid(track.kpts, SHOULDERS)
        hips = _mid(track.kpts, HIPS)
        if shoulders is not None and hips is not None:
            dx, dy = hips - shoulders
            tilt = degrees(atan2(abs(dx), abs(dy)))
            return tilt > angle, "kpts", tilt
    x1, y1, x2, y2 = track.bbox
    h = y2 - y1
    return h > 0 and (x2 - x1) / h > aspect, "bbox", None


def _center(bbox) -> np.ndarray:
    x1, y1, x2, y2 = bbox
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2])


def is_still(track: TrackState, ts: float, window: float, tol: float) -> bool:
    points = [(t, bbox) for t, bbox, _ in track.history if t >= ts - window]
    if not points or ts - points[0][0] < 0.8 * window:
        return False
    x1, y1, x2, y2 = track.bbox
    length = max(x2 - x1, y2 - y1)
    centers = np.array([_center(bbox) for _, bbox in points])
    spread = np.linalg.norm(centers - centers.mean(axis=0), axis=1).max()
    return spread < tol * length


class FallRule(Rule):
    type = "fall"
    title = "Падение и неподвижность"
    severity = "critical"
    needs_zone = False
    params = [
        {"name": "min_duration", "type": "float", "unit": "с", "default": 3.0},
        {"name": "angle", "type": "float", "unit": "град", "default": 60.0},
        {"name": "aspect", "type": "float", "unit": "ширина/высота", "default": 1.2},
        {"name": "still_window", "type": "float", "unit": "с", "default": 2.0},
        {"name": "still_tol", "type": "float", "unit": "длина тела", "default": 0.3},
    ]

    def check(self, ctx: FrameContext, cfg: RuleConfig) -> dict[int, dict]:
        angle = float(self.param(cfg, "angle"))
        aspect = float(self.param(cfg, "aspect"))
        window = float(self.param(cfg, "still_window"))
        tol = float(self.param(cfg, "still_tol"))
        violators = {}
        for track in ctx.tracks.values():
            if track.cls != "person":
                continue
            lying, pose, tilt = is_lying(track, angle, aspect)
            if lying and is_still(track, ctx.ts, window, tol):
                violators[track.track_id] = {"pose": pose, "angle": round(tilt, 1) if tilt is not None else None}
        return violators
