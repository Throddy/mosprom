"""Тестовые данные API до задачи BE-6."""
import random
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from core.schemas import CameraConfig, Event, RuleConfig, Zone

FRAME_W, FRAME_H = 1280, 720

CAMERAS = [
    CameraConfig(
        id="cam1",
        name="Склад, ряд 3",
        source="data/demo.mp4",
        fps=10,
        zones=[Zone(id="forklift_lane", name="Проезд погрузчика",
                    polygon=[(0.10, 0.40), (0.55, 0.40), (0.55, 0.95), (0.10, 0.95)])],
        rules=[
            RuleConfig(type="danger_zone", zone="forklift_lane", schedule=("07:55", "12:00"),
                       params={"min_duration": 1.0}),
            RuleConfig(type="fall", params={"min_duration": 3.0}),
        ],
    ),
    CameraConfig(
        id="cam2",
        name="Цех 1, участок сборки",
        source="data/demo.mp4",
        fps=10,
        rules=[RuleConfig(type="fall"), RuleConfig(type="running")],
    ),
]

RULES = [
    {"type": "fall", "title": "Падение и неподвижность", "severity": "critical", "needs_zone": False,
     "params": [{"name": "min_duration", "type": "float", "unit": "с", "default": 3.0}]},
    {"type": "danger_zone", "title": "Человек в опасной зоне", "severity": "high", "needs_zone": True,
     "params": [{"name": "min_duration", "type": "float", "unit": "с", "default": 1.0}]},
    {"type": "proximity", "title": "Сближение с техникой", "severity": "critical", "needs_zone": False,
     "params": [{"name": "dist", "type": "float", "unit": "рост человека", "default": 1.0},
                {"name": "min_duration", "type": "float", "unit": "с", "default": 0.5}]},
    {"type": "running", "title": "Бег в зоне работы техники", "severity": "high", "needs_zone": False,
     "params": [{"name": "speed", "type": "float", "unit": "рост человека/с", "default": 1.5},
                {"name": "min_duration", "type": "float", "unit": "с", "default": 1.0}]},
]

_rng = random.Random()


def _min_duration(rule: dict) -> float:
    return next(p["default"] for p in rule["params"] if p["name"] == "min_duration")


def make_event(ts: float, rng: random.Random | None = None) -> Event:
    rng = rng or _rng
    camera = rng.choice(CAMERAS)
    rule = rng.choice(RULES)
    w = rng.uniform(60, 250)
    h = rng.uniform(120, 450)
    x1 = rng.uniform(0, FRAME_W - w)
    y1 = rng.uniform(0, FRAME_H - h)
    return Event(
        id=uuid.UUID(int=rng.getrandbits(128), version=4).hex,
        camera_id=camera.id,
        type=rule["type"],
        severity=rule["severity"],
        track_id=rng.randint(1, 500),
        bbox=(round(x1, 1), round(y1, 1), round(x1 + w, 1), round(y1 + h, 1)),
        conf=round(rng.uniform(0.5, 0.95), 2),
        ts_start=ts - _min_duration(rule),
        ts_confirm=ts,
        ts_end=rng.choice([None, ts + rng.uniform(5, 60)]),
        zone_id="forklift_lane" if rule["type"] == "danger_zone" else None,
    )


def seed_events() -> list[Event]:
    rng = random.Random(42)
    now = time.time()
    return [make_event(now - rng.uniform(0, 7 * 24 * 3600), rng) for _ in range(40)]


def gray_frame() -> np.ndarray:
    return np.full((FRAME_H, FRAME_W, 3), 128, np.uint8)


def save_snapshot(event: Event, media_dir: Path) -> Path:
    img = gray_frame()
    cv2.putText(img, f"{event.camera_id} {event.type}", (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    x1, y1, x2, y2 = (int(v) for v in event.bbox)
    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 3)
    path = media_dir / event.camera_id / f"{event.id}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return path
