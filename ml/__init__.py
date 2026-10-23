import os
from pathlib import Path

import yaml

from core.schemas import Detector

ROOT = Path(__file__).resolve().parent.parent


def create_detector(backend: str | None = None) -> Detector:
    backend = backend or os.environ.get("DETECTOR_BACKEND", "onnx")
    models_cfg = yaml.safe_load((ROOT / "configs/models.yaml").read_text())["models"]
    # Импорт внутри ветки: import ml не должен загружать ultralytics.
    if backend == "onnx":
        from ml.backends.onnx_rt import OnnxDetector
        return OnnxDetector(models_cfg, ROOT)
    if backend == "linq":
        from ml.backends.linq import LinqDetector
        return LinqDetector(models_cfg, ROOT)
    raise ValueError(f"неизвестный бэкенд детектора: {backend}")
