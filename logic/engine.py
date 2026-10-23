"""Движок событий: трекинг, вызов правил, min_duration, одно событие на трек, закрытие через ts_end."""
import logging
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time

from core.schemas import CameraConfig, Detection, Event, RuleConfig, Track
from logic.rules import RULES
from logic.rules.base import FrameContext, TrackState
from logic.tracker import Tracker

log = logging.getLogger(__name__)

GRACE = 1.0         # с без нарушения, после которых кандидат удаляется
CLOSE_AFTER = 2.0   # с без нарушения или без трека, после которых событие закрывается
HISTORY = 10.0      # с истории трека


@dataclass
class Result:
    tracks: list[Track] = field(default_factory=list)
    new_events: list[Event] = field(default_factory=list)
    closed_events: list[Event] = field(default_factory=list)


def _parse_time(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def in_schedule(schedule: tuple[str, str], t: time) -> bool:
    """Интервал [start, end). Если start > end, интервал переходит через полночь."""
    start, end = _parse_time(schedule[0]), _parse_time(schedule[1])
    if start <= end:
        return start <= t < end
    return t >= start or t < end


class Engine:
    def __init__(self, camera: CameraConfig):
        self.camera = camera
        self.tracker = Tracker(camera.fps)
        self.lock = threading.Lock()
        self.tracks: dict[int, TrackState] = {}
        self.track_seen: dict[int, float] = {}
        self.candidates: dict[tuple, dict] = {}   # key -> {"ts_start", "last_seen"}
        self.open: dict[tuple, dict] = {}         # key -> {"event", "last_seen"}
        self.warned: set[tuple] = set()

    def update_config(self, camera: CameraConfig) -> None:
        with self.lock:
            self.camera = camera

    def process(self, ts: float, width: int, height: int, detections: list[Detection]) -> Result:
        with self.lock:
            return self._process(ts, width, height, detections)

    def _update_tracks(self, ts: float, detections: list[Detection]) -> set[int]:
        seen = set()
        for track_id, det in self.tracker.update(detections):
            state = self.tracks.get(track_id)
            if state is None:
                state = TrackState(track_id, det.cls, det.bbox, det.conf, det.kpts, deque())
                self.tracks[track_id] = state
            state.cls, state.bbox, state.conf, state.kpts = det.cls, det.bbox, det.conf, det.kpts
            state.history.append((ts, det.bbox, det.kpts))
            while state.history and state.history[0][0] < ts - HISTORY:
                state.history.popleft()
            self.track_seen[track_id] = ts
            seen.add(track_id)
        for track_id in [t for t, last in self.track_seen.items() if ts - last > CLOSE_AFTER]:
            del self.tracks[track_id]
            del self.track_seen[track_id]
        return seen

    def _rule_active(self, cfg: RuleConfig, ts: float) -> bool:
        if not cfg.enabled or cfg.type not in RULES:
            return False
        if cfg.schedule and not in_schedule(cfg.schedule, datetime.fromtimestamp(ts).time()):
            return False
        rule = RULES[cfg.type]
        if rule.needs_zone and not any(z.id == cfg.zone for z in self.camera.zones):
            key = (cfg.type, cfg.zone)
            if key not in self.warned:
                self.warned.add(key)
                log.warning("камера %s: правило %s без зоны %s пропущено", self.camera.id, cfg.type, cfg.zone)
            return False
        return True

    def _process(self, ts: float, width: int, height: int, detections: list[Detection]) -> Result:
        result = Result()
        seen = self._update_tracks(ts, detections)
        ctx = FrameContext(
            camera=self.camera, ts=ts, width=width, height=height,
            tracks={t: self.tracks[t] for t in seen},
            zones={z.id: z for z in self.camera.zones},
        )

        active_keys = set()
        for cfg in self.camera.rules:
            if not self._rule_active(cfg, ts):
                continue
            active_keys.add((cfg.type, cfg.zone))
            rule = RULES[cfg.type]
            try:
                violators = rule.check(ctx, cfg) or {}
            except Exception:
                log.exception("камера %s: ошибка правила %s", self.camera.id, cfg.type)
                violators = {}
            min_duration = float(rule.param(cfg, "min_duration"))
            for track_id, extra in violators.items():
                if track_id not in ctx.tracks:
                    continue
                key = (cfg.type, cfg.zone, track_id)
                if key in self.open:
                    self.open[key]["last_seen"] = ts
                    continue
                cand = self.candidates.setdefault(key, {"ts_start": ts, "last_seen": ts})
                cand["last_seen"] = ts
                if cand["last_seen"] - cand["ts_start"] >= min_duration:
                    track = ctx.tracks[track_id]
                    event = Event(
                        id=uuid.uuid4().hex, camera_id=self.camera.id, type=cfg.type,
                        severity=rule.severity, track_id=track_id, bbox=track.bbox, conf=track.conf,
                        ts_start=cand["ts_start"], ts_confirm=ts, zone_id=cfg.zone, extra=dict(extra or {}),
                    )
                    del self.candidates[key]
                    self.open[key] = {"event": event, "last_seen": ts}
                    result.new_events.append(event)

        for key in [k for k, c in self.candidates.items()
                    if ts - c["last_seen"] > GRACE or k[:2] not in active_keys or k[2] not in self.tracks]:
            del self.candidates[key]

        for key, item in list(self.open.items()):
            if (ts - item["last_seen"] > CLOSE_AFTER or key[2] not in self.tracks
                    or key[:2] not in active_keys):
                event = item["event"]
                event.ts_end = item["last_seen"]
                result.closed_events.append(event)
                del self.open[key]

        active: dict[int, list[str]] = {}
        for rule_type, _, track_id in self.open:
            active.setdefault(track_id, []).append(rule_type)
        result.tracks = [
            Track(track_id=t, cls=self.tracks[t].cls, bbox=self.tracks[t].bbox, active=active.get(t, []))
            for t in sorted(seen)
        ]
        return result
