import os
from pathlib import Path

import yaml

from core.schemas import Detector

ROOT = Path(__file__).resolve().parent.parent
TILES_SUFFIX = " +tiles"


def create_detector(backend: str | None = None, tiles: bool | None = None) -> Detector:
    backend = backend or os.environ.get("DETECTOR_BACKEND", "onnx")
    models_cfg = yaml.safe_load((ROOT / "configs/models.yaml").read_text())["models"]
    tiles_cfg = models_cfg["pose"]["tiles"]
    if tiles is not None:
        tiles_cfg["enabled"] = tiles
    # Импорт внутри ветки: import ml не должен загружать ultralytics.
    if backend == "onnx":
        from ml.backends.onnx_rt import OnnxDetector
        detector = OnnxDetector(models_cfg, ROOT)
        if tiles_cfg["enabled"]:
            detector.name += TILES_SUFFIX
        return detector
    if backend == "linq":
        # Ретранслятор читает свой configs/models.yaml на сервере, переопределить плитки нельзя.
        if tiles is not None:
            raise ValueError("плитки для linq задаются в configs/models.yaml ретранслятора")
        # Расчёт на TPU идёт через ml.relay на сервере Jupyter: notebooks/relay.md.
        from ml.backends.linq_relay import LinqRelayDetector
        return LinqRelayDetector()
    raise ValueError(f"неизвестный бэкенд детектора: {backend}")
