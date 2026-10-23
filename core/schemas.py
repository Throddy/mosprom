from dataclasses import dataclass, field
from typing import Protocol
import numpy as np

BBox = tuple[float, float, float, float]  # x1, y1, x2, y2 в пикселях исходного кадра

CLASSES = ("person", "car", "truck", "bus", "forklift")
SEVERITIES = ("critical", "high", "medium")

@dataclass
class Detection:
    cls: str                          # значение из CLASSES
    conf: float                       # 0..1
    bbox: BBox
    kpts: np.ndarray | None = None    # (17, 3): x, y, conf; порядок COCO; только для person

class Detector(Protocol):
    name: str                         # например "yolov8n-pose int8 linq"
    last_timing: dict[str, float]     # мс последнего infer(): "pre", "infer", "post"
    def infer(self, images: list[np.ndarray]) -> list[list[Detection]]: ...

@dataclass
class Zone:
    id: str
    name: str
    polygon: list[tuple[float, float]]    # x, y в долях кадра, 0..1

@dataclass
class RuleConfig:
    type: str                             # значение "type" из logic.rule_specs()
    enabled: bool = True
    zone: str | None = None               # Zone.id
    schedule: tuple[str, str] | None = None   # ("07:55", "12:00"), местное время
    params: dict = field(default_factory=dict)

@dataclass
class CameraConfig:
    id: str
    name: str
    source: str                           # файл, rtsp://... или папка с кадрами
    fps: float                            # частота обработки, кадр/с
    zones: list[Zone] = field(default_factory=list)
    rules: list[RuleConfig] = field(default_factory=list)

@dataclass
class Track:
    track_id: int
    cls: str
    bbox: BBox
    active: list[str] = field(default_factory=list)   # типы нарушений, идущих сейчас

@dataclass
class Event:
    id: str                    # uuid4().hex, создаёт logic
    camera_id: str
    type: str
    severity: str              # значение из SEVERITIES
    track_id: int
    bbox: BBox                 # бокс нарушителя на кадре текущего вызова process()
    conf: float
    ts_start: float            # начало нарушения
    ts_confirm: float          # нарушение длится min_duration; в этот момент уходит тревога
    ts_end: float | None = None    # None, пока нарушение продолжается
    zone_id: str | None = None
    extra: dict = field(default_factory=dict)   # данные правила для карточки события
