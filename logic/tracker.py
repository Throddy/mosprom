"""Трекер на supervision.ByteTrack. Сохраняет исходные Detection, в том числе kpts."""
import numpy as np
import supervision as sv

from core.schemas import CLASSES, Detection

LOST_SECONDS = 2.0
# ByteTrack пересчитывает буфер: max_time_lost = int(frame_rate / 30 * lost_track_buffer).
# Значение 30 * LOST_SECONDS даёт буфер round(LOST_SECONDS * fps) кадров при любом fps.
_BASE_RATE = 30


class Tracker:
    def __init__(self, fps: float):
        self._tracker = sv.ByteTrack(
            frame_rate=max(1, round(fps)),
            lost_track_buffer=round(LOST_SECONDS * _BASE_RATE),
        )

    def update(self, detections: list[Detection]) -> list[tuple[int, Detection]]:
        if detections:
            sv_dets = sv.Detections(
                xyxy=np.array([d.bbox for d in detections], dtype=float),
                confidence=np.array([d.conf for d in detections], dtype=float),
                class_id=np.array([CLASSES.index(d.cls) if d.cls in CLASSES else -1 for d in detections]),
                data={"idx": np.arange(len(detections))},
            )
        else:
            sv_dets = sv.Detections.empty()
            sv_dets.data["idx"] = np.empty(0, dtype=int)
        tracked = self._tracker.update_with_detections(sv_dets)
        if tracked.tracker_id is None or len(tracked) == 0:
            return []
        return [(int(tid), detections[int(i)]) for tid, i in zip(tracked.tracker_id, tracked.data["idx"])]
