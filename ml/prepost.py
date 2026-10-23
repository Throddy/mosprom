import cv2
import numpy as np

from core.schemas import BBox, Detection

INPUT_SIZE = 640
PAD_VALUE = 114
IOU = 0.7
NUM_KPTS = 17

Meta = tuple[float, int, int]


def preprocess(image: np.ndarray) -> tuple[np.ndarray, Meta]:
    """Кадр BGR uint8 (H, W, 3) → тензор RGB float32 0..1 формы (1, 3, 640, 640).

    Второе значение — (scale, pad_left, pad_top) для обратного перевода координат.
    """
    h, w = image.shape[:2]
    scale = min(INPUT_SIZE / h, INPUT_SIZE / w)
    new_w, new_h = round(w * scale), round(h * scale)
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    pad_left = (INPUT_SIZE - new_w) // 2
    pad_top = (INPUT_SIZE - new_h) // 2
    canvas = np.full((INPUT_SIZE, INPUT_SIZE, 3), PAD_VALUE, dtype=np.uint8)
    canvas[pad_top:pad_top + new_h, pad_left:pad_left + new_w] = resized
    tensor = canvas[:, :, ::-1].transpose(2, 0, 1)[np.newaxis].astype(np.float32) / 255.0
    return np.ascontiguousarray(tensor), (scale, pad_left, pad_top)


def postprocess_pose(output: np.ndarray, meta: Meta, frame_size: tuple[int, int],
                     conf: float, iou: float) -> list[Detection]:
    """Выход [1, 56, 8400]: cx, cy, w, h, score, 17 × (x, y, conf) в пикселях входа 640.

    frame_size — (width, height) исходного кадра.
    """
    pred = output[0]
    keep = pred[4] > conf
    boxes, scores = pred[:4, keep].T, pred[4, keep]
    kpts = pred[5:, keep].T.reshape(-1, NUM_KPTS, 3)
    return [
        Detection(cls="person", conf=float(scores[i]),
                  bbox=_to_frame_box(boxes[i], meta, frame_size),
                  kpts=_to_frame_kpts(kpts[i], meta, frame_size))
        for i in _nms(boxes, scores, None, conf, iou)
    ]


def postprocess_det(output: np.ndarray, meta: Meta, frame_size: tuple[int, int], conf: float,
                    iou: float, class_names: dict[int, str], keep: set[str]) -> list[Detection]:
    """Выход [1, 84, 8400]: cx, cy, w, h в пикселях входа 640 и 80 оценок классов COCO.

    frame_size — (width, height) исходного кадра.
    """
    pred = output[0]
    class_ids, scores = pred[4:].argmax(0), pred[4:].max(0)
    keep_ids = [i for i, name in class_names.items() if name in keep]
    mask = (scores > conf) & np.isin(class_ids, keep_ids)
    boxes, scores, class_ids = pred[:4, mask].T, scores[mask], class_ids[mask]
    return [
        Detection(cls=class_names[int(class_ids[i])], conf=float(scores[i]),
                  bbox=_to_frame_box(boxes[i], meta, frame_size))
        for i in _nms(boxes, scores, class_ids, conf, iou)
    ]


def _nms(boxes: np.ndarray, scores: np.ndarray, class_ids: np.ndarray | None, conf: float,
         iou: float) -> list[int]:
    if len(boxes) == 0:
        return []
    corners = np.column_stack([boxes[:, :2] - boxes[:, 2:] / 2, boxes[:, 2:]]).tolist()
    if class_ids is None:
        kept = cv2.dnn.NMSBoxes(corners, scores.tolist(), conf, iou)
    else:
        kept = cv2.dnn.NMSBoxesBatched(corners, scores.tolist(), class_ids.tolist(), conf, iou)
    return [int(i) for i in np.asarray(kept).reshape(-1)]


def _to_frame_box(cxcywh: np.ndarray, meta: Meta, frame_size: tuple[int, int]) -> BBox:
    cx, cy, bw, bh = (float(v) for v in cxcywh)
    xs = _to_frame(np.array([cx - bw / 2, cx + bw / 2]), meta[1], meta[0], frame_size[0])
    ys = _to_frame(np.array([cy - bh / 2, cy + bh / 2]), meta[2], meta[0], frame_size[1])
    return (float(xs[0]), float(ys[0]), float(xs[1]), float(ys[1]))


def _to_frame_kpts(kpts: np.ndarray, meta: Meta, frame_size: tuple[int, int]) -> np.ndarray:
    result = kpts.astype(np.float32)
    result[:, 0] = _to_frame(result[:, 0], meta[1], meta[0], frame_size[0])
    result[:, 1] = _to_frame(result[:, 1], meta[2], meta[0], frame_size[1])
    return result


def _to_frame(coords: np.ndarray, pad: int, scale: float, limit: int) -> np.ndarray:
    # Обратный letterbox: убрать отступ, вернуть масштаб, обрезать по кадру.
    return np.clip((coords - pad) / scale, 0, limit)
