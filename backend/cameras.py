"""Чтение и запись камер: базовый файл в git (CAMERAS_BASE, по умолчанию configs/cameras.yaml),
изменения из интерфейса в файле правок (CAMERAS_PATH, по умолчанию configs/cameras.local.yaml)."""
import os
import tempfile
from pathlib import Path

import yaml

from core.schemas import CameraConfig, RuleConfig, Zone

ROOT = Path(__file__).resolve().parent.parent
CAMERAS_PATH = ROOT / "configs" / "cameras.yaml"
LOCAL_PATH = "configs/cameras.local.yaml"


def cameras_path() -> Path:
    path = Path(os.environ.get("CAMERAS_PATH") or LOCAL_PATH)
    return path if path.is_absolute() else ROOT / path


def base_path() -> Path:
    """CAMERAS_BASE: базовый файл камер, если файла правок ещё нет."""
    value = os.environ.get("CAMERAS_BASE")
    if not value:
        return CAMERAS_PATH
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_active() -> list[CameraConfig]:
    """Камеры из файла правок cameras_path(), если он есть, иначе из базового base_path()."""
    path = cameras_path()
    return load_cameras(path if path.exists() else base_path())


def load_cameras(path: Path = CAMERAS_PATH) -> list[CameraConfig]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cameras = []
    for c in data.get("cameras", []):
        zones = [Zone(id=z["id"], name=z["name"], polygon=[tuple(p) for p in z["polygon"]])
                 for z in c.get("zones") or []]
        rules = [RuleConfig(type=r["type"], enabled=r.get("enabled", True), zone=r.get("zone"),
                            schedule=tuple(r["schedule"]) if r.get("schedule") else None,
                            params=r.get("params") or {})
                 for r in c.get("rules") or []]
        cameras.append(CameraConfig(id=c["id"], name=c["name"], source=c["source"], fps=c["fps"],
                                    zones=zones, rules=rules))
    return cameras


def save_cameras(path: Path, cameras: list[CameraConfig]) -> None:
    data = {"cameras": [
        {
            "id": c.id,
            "name": c.name,
            "source": c.source,
            "fps": c.fps,
            "zones": [{"id": z.id, "name": z.name, "polygon": [list(p) for p in z.polygon]} for z in c.zones],
            "rules": [{"type": r.type, "enabled": r.enabled, "zone": r.zone,
                       "schedule": list(r.schedule) if r.schedule else None, "params": r.params}
                      for r in c.rules],
        }
        for c in cameras
    ]}
    # Атомарная запись: временный файл в той же папке, затем os.replace
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
