from collections.abc import Callable

import cv2
import numpy as np

from core.schemas import Detection

Region = tuple[int, int, int, int]          # x0, y0, x1, y1 в пикселях исходного кадра
Model = Callable[[list[np.ndarray]], list[list[Detection]]]

MERGE_IOU = 0.5
EDGE_MARGIN_PX = 2


def tile_regions(w: int, h: int, rows: int, cols: int, overlap: float) -> list[Region]:
    """Сетка rows × cols плиток кадра w × h; соседние плитки перекрываются на долю overlap."""
    tile_w = w / (cols - (cols - 1) * overlap)
    tile_h = h / (rows - (rows - 1) * overlap)
    regions = []
    for row in range(rows):
        for col in range(cols):
            x0, y0 = round(col * tile_w * (1 - overlap)), round(row * tile_h * (1 - overlap))
            regions.append((x0, y0, min(w, round(x0 + tile_w)), min(h, round(y0 + tile_h))))
    return regions


def run_on_regions(model: Model, frame: np.ndarray, regions: list[Region]) -> list[list[Detection]]:
    """Детекции model по каждой области кадра в полном разрешении, в координатах кадра."""
    if not regions:
        return []
    crops = [frame[y0:y1, x0:x1] for x0, y0, x1, y1 in regions]
    return [[_shift(d, x0, y0) for d in found]
            for (x0, y0, _, _), found in zip(regions, model(crops))]


def needs_tiles(persons: list[Detection], frame_h: int, trigger_max_h: float) -> bool:
    """Людей нет или самый высокий ниже trigger_max_h высоты кадра."""
    heights = [d.bbox[3] - d.bbox[1] for d in persons]
    return not heights or max(heights) < trigger_max_h * frame_h


def add_tile_persons(frame: np.ndarray, persons: list[Detection], model: Model,
                     tiles: dict | None) -> list[Detection]:
    """Люди полного кадра плюс люди из плиток, если на кадре люди мелкие или их нет."""
    h, w = frame.shape[:2]
    if not tiles or not tiles["enabled"] or not needs_tiles(persons, h, tiles["trigger_max_h"]):
        return persons
    regions = tile_regions(w, h, tiles["rows"], tiles["cols"], tiles["overlap"])
    found = run_on_regions(model, frame, regions)
    inner = [d for region, dets in zip(regions, found) for d in dets
             if not _touches_inner_edge(d.bbox, region, w, h)]
    return nms(persons + inner, MERGE_IOU)


def nms(detections: list[Detection], iou: float) -> list[Detection]:
    if len(detections) < 2:
        return detections
    boxes = [[d.bbox[0], d.bbox[1], d.bbox[2] - d.bbox[0], d.bbox[3] - d.bbox[1]]
             for d in detections]
    kept = cv2.dnn.NMSBoxes(boxes, [d.conf for d in detections], 0.0, iou)
    return [detections[int(i)] for i in np.asarray(kept).reshape(-1)]


def _touches_inner_edge(bbox, region: Region, w: int, h: int) -> bool:
    # Край плитки внутри кадра режет человека: целиком он виден в соседней плитке.
    x0, y0, x1, y1 = region
    bx1, by1, bx2, by2 = bbox
    return ((x0 > 0 and bx1 - x0 < EDGE_MARGIN_PX) or (y0 > 0 and by1 - y0 < EDGE_MARGIN_PX)
            or (x1 < w and x1 - bx2 < EDGE_MARGIN_PX) or (y1 < h and y1 - by2 < EDGE_MARGIN_PX))


def _shift(detection: Detection, x0: int, y0: int) -> Detection:
    x1, y1, x2, y2 = detection.bbox
    kpts = None
    if detection.kpts is not None:
        kpts = detection.kpts.copy()
        kpts[:, 0] += x0
        kpts[:, 1] += y0
    return Detection(cls=detection.cls, conf=detection.conf,
                     bbox=(x1 + x0, y1 + y0, x2 + x0, y2 + y0), kpts=kpts)
