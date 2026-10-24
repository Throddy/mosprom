"""Снимок события: кадр с выделенным нарушителем. Текст только латиницей."""
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from backend.privacy import blur_enabled, blur_people
from core.schemas import Event

MEDIA_DIR = Path(__file__).resolve().parent / "media"
RED = (0, 0, 255)
WHITE = (255, 255, 255)


def snapshot_path(camera_id: str, event_id: str) -> str:
    """Путь снимка внутри /media."""
    return f"{camera_id}/{event_id}.jpg"


def save_snapshot(frame: np.ndarray, event: Event, camera_id: str, detections=None) -> str:
    # На демо-стенде (BLUR_FACES=1) головы людей размываются до рисования рамки нарушителя
    img = blur_people(frame, detections) if blur_enabled() and detections else frame.copy()
    x1, y1, x2, y2 = (int(v) for v in event.bbox)
    cv2.rectangle(img, (x1, y1), (x2, y2), RED, 3)
    cv2.putText(img, f"{event.type} id {event.track_id}", (x1, max(y1 - 8, 20)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, RED, 2)
    stamp = datetime.fromtimestamp(event.ts_confirm).strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(img, f"{camera_id} {stamp}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, WHITE, 2)
    rel = snapshot_path(camera_id, event.id)
    path = MEDIA_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return rel
