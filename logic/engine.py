"""Движок событий: трекинг, вызов правил, min_duration, одно событие на трек, закрытие через ts_end.

Подавление повторов: новое событие не создаётся, если на камере есть событие того же типа и зоны,
открытое или закрытое не более REPEAT_WINDOW с назад, и точка ног нового трека ближе
REPEAT_DIST высот его бокса к последней позиции того нарушения. Открытое событие трека, которого
нет в кадре, продолжается новым треком без нового event_new. Закрытое событие не открывается заново:
новое только подавляется, сохранённое событие не меняется.
"""
import logging
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time

from core.schemas import CameraConfig, Detection, Event, RuleConfig, Track
from logic.geometry import bbox_height, foot_point
from logic.rules import RULES
from logic.rules.base import FrameContext, TrackState
from logic.tracker import Tracker

log = logging.getLogger(__name__)

GRACE = 1.0         # с без нарушения, после которых кандидат удаляется
CLOSE_AFTER = 2.0   # с без нарушения или без трека, после которых событие закрывается
HISTORY = 10.0      # с истории трека
REPEAT_WINDOW = 10.0  # с после закрытия, в течение которых новое событие рядом считается повтором
REPEAT_DIST = 1.0     # расстояние до прежнего нарушения в высотах бокса нового трека


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
        self.broken: set[tuple] = set()
        # Закрытые события для сопоставления повторов: {"type", "zone", "foot", "ts_end"}
        self.recent: list[dict] = []
        # Подавленные эпизоды: key -> {"last_seen", "ref"}, ref — запись recent или открытое событие
        self.suppressed: dict[tuple, dict] = {}
        self.suppressed_counts: dict[str, int] = {}

    def update_config(self, camera: CameraConfig) -> None:
        with self.lock:
            self.camera = camera
            self.broken.clear()

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

    def _apply_rule(self, cfg: RuleConfig, ctx: FrameContext, ts: float, result: Result) -> bool:
        """Проверяет одно правило и обновляет его состояния. False, если правило неактивно."""
        if not self._rule_active(cfg, ts):
            return False
        rule = RULES[cfg.type]
        min_duration = float(rule.param(cfg, "min_duration"))
        try:
            violators = rule.check(ctx, cfg) or {}
        except Exception:
            log.exception("камера %s: ошибка правила %s", self.camera.id, cfg.type)
            violators = {}
        for track_id, extra in violators.items():
            if track_id not in ctx.tracks:
                continue
            key = (cfg.type, cfg.zone, track_id)
            foot = foot_point(ctx.tracks[track_id].bbox)
            if key in self.open:
                self.open[key]["last_seen"] = ts
                self.open[key]["foot"] = foot
                continue
            if key in self.suppressed:
                # Подавленный эпизод продолжается: позиция и время прежнего нарушения обновляются
                item = self.suppressed[key]
                item["last_seen"] = ts
                if "ts_end" in item["ref"]:
                    item["ref"]["foot"], item["ref"]["ts_end"] = foot, ts
                continue
            cand = self.candidates.setdefault(key, {"ts_start": ts, "last_seen": ts})
            cand["last_seen"] = ts
            if cand["last_seen"] - cand["ts_start"] >= min_duration:
                track = ctx.tracks[track_id]
                del self.candidates[key]
                if self._repeat(key, track.bbox, ts, ctx):
                    continue
                event = Event(
                    id=uuid.uuid4().hex, camera_id=self.camera.id, type=cfg.type,
                    severity=rule.severity, track_id=track_id, bbox=track.bbox, conf=track.conf,
                    ts_start=cand["ts_start"], ts_confirm=ts, zone_id=cfg.zone, extra=dict(extra or {}),
                )
                self.open[key] = {"event": event, "last_seen": ts, "foot": foot}
                result.new_events.append(event)
        return True

    def _repeat(self, key: tuple, bbox, ts: float, ctx: FrameContext) -> bool:
        """Повтор прежнего нарушения: продолжить открытое событие или подавить новое. True, если не создавать."""
        rule_type, zone, track_id = key
        fx, fy = foot_point(bbox)
        limit = REPEAT_DIST * bbox_height(bbox)
        best, best_d = None, None
        for other, item in self.open.items():
            if other[:2] == (rule_type, zone) and other[2] != track_id:
                d = ((item["foot"][0] - fx) ** 2 + (item["foot"][1] - fy) ** 2) ** 0.5
                if d < limit and (best_d is None or d < best_d):
                    best, best_d = ("open", other), d
        for rec in self.recent:
            if (rec["type"], rec["zone"]) == (rule_type, zone) and ts - rec["ts_end"] <= REPEAT_WINDOW:
                d = ((rec["foot"][0] - fx) ** 2 + (rec["foot"][1] - fy) ** 2) ** 0.5
                if d < limit and (best_d is None or d < best_d):
                    best, best_d = ("closed", rec), d
        if best is None:
            return False
        self.suppressed_counts[rule_type] = self.suppressed_counts.get(rule_type, 0) + 1
        kind, ref = best
        if kind == "open" and ref[2] not in ctx.tracks:
            # Трек прежнего события пропал из кадра: событие продолжается новым треком
            item = self.open.pop(ref)
            item["last_seen"], item["foot"] = ts, (fx, fy)
            self.open[key] = item
            log.info("камера %s: %s трек %s продолжает событие %s трека %s", self.camera.id, rule_type,
                     track_id, item["event"].id, ref[2])
        elif kind == "open":
            self.suppressed[key] = {"last_seen": ts, "ref": self.open[ref]}
            log.info("камера %s: %s трек %s подавлен: рядом открытое событие трека %s", self.camera.id,
                     rule_type, track_id, ref[2])
        else:
            ref["foot"], ref["ts_end"] = (fx, fy), ts
            self.suppressed[key] = {"last_seen": ts, "ref": ref}
            log.info("камера %s: %s трек %s подавлен: повтор закрытого события, закрытое заново не открывается",
                     self.camera.id, rule_type, track_id)
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
            # Ошибка одного правила (битое расписание, нечисловой параметр) не останавливает камеру:
            # правило пропускается, его открытые события закрываются как у выключенного.
            try:
                if self._apply_rule(cfg, ctx, ts, result):
                    active_keys.add((cfg.type, cfg.zone))
            except Exception as e:
                key = (self.camera.id, cfg.type)
                if key not in self.broken:
                    self.broken.add(key)
                    log.warning("камера %s: правило %s пропущено: %s", self.camera.id, cfg.type, e)

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
                self.recent.append({"type": key[0], "zone": key[1], "foot": item["foot"],
                                    "ts_end": item["last_seen"]})

        for key in [k for k, item in self.suppressed.items()
                    if ts - item["last_seen"] > CLOSE_AFTER or k[2] not in self.tracks or k[:2] not in active_keys]:
            del self.suppressed[key]
        # Записи старше REPEAT_WINDOW больше не нужны для сопоставления
        self.recent = [r for r in self.recent if ts - r["ts_end"] <= REPEAT_WINDOW]

        active: dict[int, list[str]] = {}
        for rule_type, _, track_id in self.open:
            active.setdefault(track_id, []).append(rule_type)
        result.tracks = [
            Track(track_id=t, cls=self.tracks[t].cls, bbox=self.tracks[t].bbox, active=active.get(t, []))
            for t in sorted(seen)
        ]
        return result
