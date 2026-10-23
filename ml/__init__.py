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
        # Расчёт на TPU идёт через ml.relay на сервере Jupyter: notebooks/relay.md.
        from ml.backends.linq_relay import LinqRelayDetector
        return LinqRelayDetector()
    raise ValueError(f"неизвестный бэкенд детектора: {backend}")
