"""Размытие лиц на демо-стенде: голова каждого человека пикселизируется."""
import os

import cv2
import numpy as np

from core.schemas import Detection

HEAD_POINTS = (0, 1, 2, 3, 4)  # нос, глаза, уши
KPT_CONF = 0.3
PIXELS = 8


def blur_enabled() -> bool:
    return os.environ.get("BLUR_FACES", "0") == "1"


def head_box(det: Detection) -> tuple[int, int, int, int]:
    """Область головы: квадрат по точкам головы или верхние 22 % бокса."""
    x1, y1, x2, y2 = det.bbox
    kpts = det.kpts
    if isinstance(kpts, np.ndarray) and kpts.shape == (17, 3):
        pts = np.array([kpts[i, :2] for i in HEAD_POINTS if kpts[i, 2] > KPT_CONF])
        if len(pts) >= 2:
            cx, cy = pts.mean(axis=0)
            spread = float(np.max(np.linalg.norm(pts[:, None] - pts[None, :], axis=2)))
            side = 2.5 * max(spread, 0.08 * (y2 - y1))
            return (int(cx - side / 2), int(cy - side / 2), int(cx + side / 2), int(cy + side / 2))
    return (int(x1), int(y1), int(x2), int(y1 + 0.22 * (y2 - y1)))


def blur_people(frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
    """Копия кадра, у каждого person область головы пикселизирована."""
    out = frame.copy()
    h, w = out.shape[:2]
    for det in detections:
        if det.cls != "person":
            continue
        x1, y1, x2, y2 = head_box(det)
        x1, y1 = max(x1, 0), max(y1, 0)
        x2, y2 = min(x2, w), min(y2, h)
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        region = out[y1:y2, x1:x2]
        small = cv2.resize(region, (PIXELS, PIXELS), interpolation=cv2.INTER_LINEAR)
        out[y1:y2, x1:x2] = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
    return out


def blur_top(frame: np.ndarray, share: float = 0.4) -> np.ndarray:
    """Копия кадра с пикселизированной верхней частью: когда для кадра нет результатов детектора."""
    out = frame.copy()
    h, w = out.shape[:2]
    y2 = max(int(h * share), 2)
    small = cv2.resize(out[:y2], (max(w // 40, 2), max(y2 // 40, 2)), interpolation=cv2.INTER_LINEAR)
    out[:y2] = cv2.resize(small, (w, y2), interpolation=cv2.INTER_NEAREST)
    return out
