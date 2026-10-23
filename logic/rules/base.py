"""Базовые типы правил нарушений."""
from collections import deque
from dataclasses import dataclass

import numpy as np

from core.schemas import BBox, CameraConfig, RuleConfig, Zone


@dataclass
class TrackState:
    track_id: int
    cls: str
    bbox: BBox
    conf: float
    kpts: np.ndarray | None
    history: deque          # (ts, bbox, kpts), последние 10 с


@dataclass
class FrameContext:
    camera: CameraConfig
    ts: float
    width: int
    height: int
    tracks: dict[int, TrackState]
    zones: dict[str, Zone]


class Rule:
    type: str
    title: str
    severity: str           # из SEVERITIES
    needs_zone: bool
    params: list[dict]      # формат раздела 5 контракта; всегда есть "min_duration"

    def check(self, ctx: FrameContext, cfg: RuleConfig) -> dict[int, dict]:
        """track_id нарушителей в этом кадре -> extra для карточки события."""
        raise NotImplementedError

    def param(self, cfg: RuleConfig, name: str):
        """cfg.params[name], иначе default из self.params."""
        if name in cfg.params:
            return cfg.params[name]
        for p in self.params:
            if p["name"] == name:
                return p.get("default")
        raise KeyError(name)
