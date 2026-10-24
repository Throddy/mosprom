"""Геометрия для правил: точка в полигоне, точка ног, высота бокса."""
import numpy as np

from core.schemas import BBox


def point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """Метод лучей. Точка на границе считается внутри."""
    n = len(polygon)
    if n < 3:
        return False
    pts = np.asarray(polygon, dtype=float)
    inside = False
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        # Граница: точка на отрезке
        cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
        if abs(cross) < 1e-9 and min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 \
                and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9:
            return True
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def foot_point(bbox: BBox) -> tuple[float, float]:
    x1, _, x2, y2 = bbox
    return (x1 + x2) / 2, y2


def bbox_height(bbox: BBox) -> float:
    return bbox[3] - bbox[1]
