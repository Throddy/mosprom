"""Чтение и запись configs/cameras.yaml."""
from pathlib import Path

import yaml

from core.schemas import CameraConfig, RuleConfig, Zone

ROOT = Path(__file__).resolve().parent.parent
CAMERAS_PATH = ROOT / "configs" / "cameras.yaml"


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
    Path(path).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
