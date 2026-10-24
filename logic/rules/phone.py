"""Телефон при работе: центр бокса телефона внутри бокса человека и рядом с его запястьем."""
from core.schemas import RuleConfig
from logic.geometry import bbox_height, foot_point, point_in_polygon
from logic.rules.base import FrameContext, Rule, TrackState

PHONE = "phone"
WRISTS = (9, 10)        # левое и правое запястье, порядок точек COCO
WRIST_CONF = 0.3


def box_center(bbox) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2, (y1 + y2) / 2


def visible_wrists(kpts) -> list[tuple[float, float]]:
    if kpts is None:
        return []
    return [(float(kpts[i, 0]), float(kpts[i, 1])) for i in WRISTS if kpts[i, 2] >= WRIST_CONF]


def phone_in_hand(person_bbox, wrists: list[tuple[float, float]], phone_bbox, limit: float) -> bool:
    """Центр бокса телефона внутри бокса человека и не дальше limit пикселей от запястья."""
    cx, cy = box_center(phone_bbox)
    x1, y1, x2, y2 = person_bbox
    if not (x1 <= cx <= x2 and y1 <= cy <= y2):
        return False
    return min(((cx - wx) ** 2 + (cy - wy) ** 2) ** 0.5 for wx, wy in wrists) <= limit


class PhoneRule(Rule):
    type = "phone"
    title = "Телефон при работе"
    severity = "medium"
    needs_zone = False
    params = [
        {"name": "hand_dist", "type": "float", "unit": "рост человека", "default": 0.3},
        {"name": "min_duration", "type": "float", "unit": "с", "default": 2.0},
        {"name": "hold", "type": "float", "unit": "с", "default": 1.0},
    ]

    def __init__(self) -> None:
        # Экземпляр правила один на все камеры, поэтому состояние разделено по камерам:
        # camera_id -> {(zone, track_id): {"last": ts телефона у руки, "phone_conf": максимум}}
        self._seen: dict[str, dict[tuple, dict]] = {}
        self._clock: dict[str, float] = {}

    def check(self, ctx: FrameContext, cfg: RuleConfig) -> dict[int, dict]:
        hand_dist = float(self.param(cfg, "hand_dist"))
        hold = float(self.param(cfg, "hold"))
        zone = ctx.zones.get(cfg.zone) if cfg.zone else None
        phones = [t for t in ctx.tracks.values() if t.cls == PHONE]
        seen = self._seen.setdefault(ctx.camera.id, {})
        # Время камеры пошло назад: новый прогон (следующее видео офлайн-оценки), треки уже другие
        if ctx.ts < self._clock.get(ctx.camera.id, ctx.ts):
            seen.clear()
        self._clock[ctx.camera.id] = ctx.ts
        violators = {}
        for track in ctx.tracks.values():
            if track.cls != "person":
                continue
            x, y = foot_point(track.bbox)
            in_zone = zone is None or point_in_polygon(x / ctx.width, y / ctx.height, zone.polygon)
            if not in_zone:
                continue
            key = (cfg.zone, track.track_id)
            _mark_phone_in_hand(seen, key, track, phones, hand_dist, ctx.ts)
            state = seen.get(key)
            if state is not None and ctx.ts - state["last"] <= hold:
                violators[track.track_id] = {"phone_conf": round(state["phone_conf"], 2)}
        # Нарушение закончилось: следующее начнётся с новым максимумом уверенности
        for key in [k for k, s in seen.items() if k[0] == cfg.zone and ctx.ts - s["last"] > hold]:
            del seen[key]
        return violators


def _mark_phone_in_hand(seen: dict[tuple, dict], key: tuple, person: TrackState,
                        phones: list[TrackState], hand_dist: float, ts: float) -> None:
    h = bbox_height(person.bbox)
    wrists = visible_wrists(person.kpts)
    # Без видимых запястий трек на этом кадре не проверяется: нарушение держится по hold.
    if h <= 0 or not wrists:
        return
    confs = [p.conf for p in phones if phone_in_hand(person.bbox, wrists, p.bbox, hand_dist * h)]
    if not confs:
        return
    state = seen.setdefault(key, {"last": ts, "phone_conf": 0.0})
    state["last"] = ts
    state["phone_conf"] = max(state["phone_conf"], max(confs))
