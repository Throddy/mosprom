"""Разметка кадра для /stream: зоны, люди со скелетом, техника. Текст только латиницей."""
import cv2
import numpy as np

from core.schemas import Detection, Track, Zone

RED = (0, 0, 255)
GREEN = (0, 255, 0)
ORANGE = (0, 165, 255)
WHITE = (255, 255, 255)
VEHICLES = ("car", "truck", "bus", "forklift")
KPT_CONF = 0.5

# Пары точек COCO для скелета
SKELETON = [
    (15, 13), (13, 11), (16, 14), (14, 12), (11, 12), (5, 11), (6, 12), (5, 6), (5, 7),
    (6, 8), (7, 9), (8, 10), (1, 2), (0, 1), (0, 2), (1, 3), (2, 4), (3, 5), (4, 6),
]


def draw(frame: np.ndarray, detections: list[Detection], zones: list[Zone], info: str,
         tracks: list[Track] | None = None) -> np.ndarray:
    img = frame.copy()
    h, w = img.shape[:2]
    for zone in zones:
        pts = np.array([[x * w, y * h] for x, y in zone.polygon], np.int32)
        cv2.polylines(img, [pts], True, RED, 2)
    for det in detections:
        x1, y1, x2, y2 = (int(v) for v in det.bbox)
        if det.cls == "person":
            cv2.rectangle(img, (x1, y1), (x2, y2), GREEN, 2)
            if det.kpts is not None:
                _skeleton(img, det.kpts)
        elif det.cls in VEHICLES:
            cv2.rectangle(img, (x1, y1), (x2, y2), ORANGE, 2)
            cv2.putText(img, det.cls, (x1, max(y1 - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, ORANGE, 2)
    for track in tracks or []:
        x1, y1, x2, y2 = (int(v) for v in track.bbox)
        color = RED if track.active else WHITE
        if track.active:
            cv2.rectangle(img, (x1, y1), (x2, y2), RED, 3)
        cv2.putText(img, f"id {track.track_id}", (x1, min(y2 + 20, h - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    cv2.putText(img, info, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, WHITE, 2)
    return img


def _skeleton(img: np.ndarray, kpts: np.ndarray) -> None:
    visible = kpts[:, 2] > KPT_CONF
    for a, b in SKELETON:
        if visible[a] and visible[b]:
            pa = (int(kpts[a, 0]), int(kpts[a, 1]))
            pb = (int(kpts[b, 0]), int(kpts[b, 1]))
            cv2.line(img, pa, pb, GREEN, 2)
    for x, y, conf in kpts:
        if conf > KPT_CONF:
            cv2.circle(img, (int(x), int(y)), 3, GREEN, -1)
