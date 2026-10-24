from pathlib import Path

import numpy as np
from ultralytics import YOLO
from ultralytics.engine.results import Results

from core.schemas import BBox, Detection
from ml.crops import Model, add_tile_persons
from ml.hands import add_hand_phones
from ml.prepost import keep_by_class_conf, lowest_conf


class OnnxDetector:
    name = "yolov8n-pose+yolov8n onnx cpu"

    def __init__(self, models_cfg: dict, root: Path) -> None:
        pose_cfg, det_cfg = models_cfg["pose"], models_cfg["det"]
        self._pose = YOLO(str(root / pose_cfg["weights"]), task="pose")
        self._det = YOLO(str(root / det_cfg["weights"]), task="detect")
        self._det_classes = det_cfg["classes"]
        self._det_conf = det_cfg["conf"]
        self._class_conf = det_cfg.get("class_conf", {})
        self._phone_crop = det_cfg.get("phone_crop")
        self._pose_args = {"imgsz": pose_cfg["imgsz"], "conf": pose_cfg["conf"]}
        self._tiles = pose_cfg.get("tiles")
        self._det_args = {
            "imgsz": det_cfg["imgsz"],
            "conf": lowest_conf(self._det_conf, self._class_conf),
            "classes": list(self._det_classes),
        }
        self.last_timing = {"pre": 0.0, "infer": 0.0, "post": 0.0}

    def infer(self, images: list[np.ndarray]) -> list[list[Detection]]:
        timing = {"pre": 0.0, "infer": 0.0, "post": 0.0}
        detections = []
        # ONNX экспортирован с batch 1, поэтому кадры обрабатываются по одному.
        for image in images:
            pose_result = _predict(self._pose, image, self._pose_args, timing)
            det_result = _predict(self._det, image, self._det_args, timing)
            persons = add_tile_persons(image, _persons(pose_result), self._pose_model(timing),
                                       self._tiles)
            objects = add_hand_phones(image, persons, self._objects(det_result),
                                      self._det_model(timing), self._phone_crop,
                                      self._class_conf.get("phone", self._det_conf))
            detections.append(persons + objects)
        self.last_timing = timing
        return detections

    def _pose_model(self, timing: dict[str, float]) -> Model:
        def run(crops: list[np.ndarray]) -> list[list[Detection]]:
            return [_persons(_predict(self._pose, crop, self._pose_args, timing)) for crop in crops]
        return run

    def _det_model(self, timing: dict[str, float]) -> Model:
        def run(crops: list[np.ndarray]) -> list[list[Detection]]:
            return [self._objects(_predict(self._det, crop, self._det_args, timing))
                    for crop in crops]
        return run

    def _objects(self, result: Results) -> list[Detection]:
        boxes = result.boxes.cpu().numpy()
        objects = [
            Detection(cls=self._det_classes[int(boxes.cls[j])], conf=float(boxes.conf[j]),
                      bbox=_bbox(boxes.xyxy[j]))
            for j in range(len(boxes))
        ]
        return keep_by_class_conf(objects, self._det_conf, self._class_conf)


def _predict(model: YOLO, image: np.ndarray, args: dict, timing: dict[str, float]) -> Results:
    result = model.predict(image, device="cpu", verbose=False, **args)[0]
    timing["pre"] += result.speed["preprocess"]
    timing["infer"] += result.speed["inference"]
    timing["post"] += result.speed["postprocess"]
    return result


def _persons(result: Results) -> list[Detection]:
    boxes = result.boxes.cpu().numpy()
    keypoints = result.keypoints.cpu().numpy()
    return [
        Detection(cls="person", conf=float(boxes.conf[j]), bbox=_bbox(boxes.xyxy[j]),
                  kpts=keypoints.data[j])
        for j in range(len(boxes))
    ]


def _bbox(xyxy: np.ndarray) -> BBox:
    x1, y1, x2, y2 = (float(v) for v in xyxy)
    return (x1, y1, x2, y2)
