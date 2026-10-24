import numpy as np

from core.schemas import Detection
from ml.crops import MERGE_IOU, Model, Region, nms, run_on_regions

WRISTS = (9, 10)            # левое и правое запястье, порядок точек COCO
WRIST_CONF = 0.3
JOIN_WRISTS = 0.25          # запястья ближе этой доли роста дают одну общую область
PHONE = "phone"


def add_hand_phones(frame: np.ndarray, persons: list[Detection], objects: list[Detection],
                    model: Model, phone_crop: dict | None, phone_conf: float) -> list[Detection]:
    """Объекты полного кадра; телефоны дополняются найденными в областях рук и проходят NMS."""
    if not phone_crop or not phone_crop["enabled"]:
        return objects
    h, w = frame.shape[:2]
    regions = hand_regions(persons, w, h, phone_crop["side"], phone_crop["min_side"],
                           phone_crop["max_side"], phone_crop["max_crops"])
    found = [d for dets in run_on_regions(model, frame, regions) for d in dets
             if d.cls == PHONE and d.conf >= phone_conf]
    phones = [d for d in objects if d.cls == PHONE] + found
    return [d for d in objects if d.cls != PHONE] + nms(phones, MERGE_IOU)


def hand_regions(persons: list[Detection], frame_w: int, frame_h: int, side: float,
                 min_side: int, max_side: int, max_crops: int) -> list[Region]:
    """Квадраты вокруг видимых запястий людей, по убыванию роста, не больше max_crops."""
    regions = []
    for person in sorted(persons, key=_height, reverse=True):
        h = _height(person)
        s = min(max(side * h, min_side), max_side)
        regions += [_square(cx, cy, s, frame_w, frame_h) for cx, cy in _hand_centers(person, h)]
    return regions[:max_crops]


def _hand_centers(person: Detection, h: float) -> list[tuple[float, float]]:
    if person.kpts is None:
        return []
    wrists = [(float(person.kpts[i, 0]), float(person.kpts[i, 1]))
              for i in WRISTS if person.kpts[i, 2] >= WRIST_CONF]
    if len(wrists) == 2:
        (x1, y1), (x2, y2) = wrists
        if ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5 < JOIN_WRISTS * h:
            return [((x1 + x2) / 2, (y1 + y2) / 2)]
    return wrists


def _square(cx: float, cy: float, s: float, frame_w: int, frame_h: int) -> Region:
    half = s / 2
    return (max(0, round(cx - half)), max(0, round(cy - half)),
            min(frame_w, round(cx + half)), min(frame_h, round(cy + half)))


def _height(person: Detection) -> float:
    return person.bbox[3] - person.bbox[1]
