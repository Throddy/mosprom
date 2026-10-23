import cv2
import numpy as np

INPUT_SIZE = 640
PAD_VALUE = 114


def preprocess(image: np.ndarray) -> tuple[np.ndarray, tuple[float, int, int]]:
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
