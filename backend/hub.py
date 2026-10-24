"""Хранилище событий поверх EventDB и рассылка событий по WebSocket."""
import dataclasses

from fastapi import WebSocket

from backend.db import EventDB
from backend.fixtures import RULES
from core.schemas import SEVERITIES, CameraConfig, Event
from logic import describe

STATUSES = ("new", "confirmed", "false", "forwarded")
EVENT_FIELDS = [f.name for f in dataclasses.fields(Event)]


def to_json(value):
    if dataclasses.is_dataclass(value):
        value = dataclasses.asdict(value)
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    return value


class Store:
    def __init__(self, cameras: list[CameraConfig], db: EventDB):
        self.cameras = {c.id: c for c in cameras}
        self.db = db

    def rule_specs(self) -> list[dict]:
        return describe() or RULES

    def zone_name(self, camera_id: str, zone_id: str | None) -> str | None:
        camera = self.cameras.get(camera_id)
        if camera is None or zone_id is None:
            return None
        return next((z.name for z in camera.zones if z.id == zone_id), None)

    def event_view(self, row: dict) -> dict:
        camera = self.cameras.get(row["camera_id"])
        titles = {r["type"]: r["title"] for r in self.rule_specs()}
        view = {name: to_json(row[name]) for name in EVENT_FIELDS}
        view.update(
            camera_name=camera.name if camera else None,
            title=titles.get(row["type"], row["type"]),
            zone_name=self.zone_name(row["camera_id"], row["zone_id"]),
            status=row["status"],
            comment=row["comment"],
            snapshot_url="/media/" + row["snapshot"],
            clip_url=None,
        )
        return view

    def add_event(self, event: Event, snapshot: str) -> dict:
        self.db.insert(event, snapshot)
        return self.event_view(self.db.get(event.id))

    def close_event(self, event_id: str, ts_end: float) -> dict | None:
        self.db.close(event_id, ts_end)
        row = self.db.get(event_id)
        return self.event_view(row) if row else None

    def set_status(self, event_id: str, status: str, comment: str | None) -> dict | None:
        if not self.db.set_status(event_id, status, comment):
            return None
        return self.event_view(self.db.get(event_id))

    def list_events(self, **filters) -> tuple[list[dict], int]:
        rows, total = self.db.query(**filters)
        return [self.event_view(r) for r in rows], total

    def stats(self, ts_from: float | None = None, ts_to: float | None = None) -> dict:
        result = self.db.stats(ts_from, ts_to)
        # Известные значения с нулями, чтобы фронтенд видел все категории
        zeros = {
            "by_type": [r["type"] for r in self.rule_specs()],
            "by_camera": list(self.cameras),
            "by_severity": list(SEVERITIES),
            "by_status": list(STATUSES),
        }
        for key, names in zeros.items():
            result[key] = {**{n: 0 for n in names}, **result[key]}
        return result


class Hub:
    def __init__(self):
        self.clients: list[WebSocket] = []

    def add(self, ws: WebSocket) -> None:
        self.clients.append(ws)

    def remove(self, ws: WebSocket) -> None:
        if ws in self.clients:
            self.clients.remove(ws)

    async def broadcast(self, kind: str, event: dict) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json({"kind": kind, "event": event})
            except Exception:
                self.remove(ws)
