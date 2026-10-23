"""Хранилище в памяти и рассылка событий по WebSocket."""
import dataclasses

from fastapi import WebSocket

from backend.fixtures import RULES
from core.schemas import CameraConfig, Event


def to_json(value):
    if dataclasses.is_dataclass(value):
        value = dataclasses.asdict(value)
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    return value


class Store:
    def __init__(self, cameras: list[CameraConfig], events: list[Event]):
        self.cameras = {c.id: c for c in cameras}
        self.events = {e.id: e for e in events}
        self.status: dict[str, str] = {}
        self.comment: dict[str, str | None] = {}
        self.titles = {r["type"]: r["title"] for r in RULES}

    def add_event(self, event: Event) -> None:
        self.events[event.id] = event

    def zone_name(self, camera_id: str, zone_id: str | None) -> str | None:
        camera = self.cameras.get(camera_id)
        if camera is None or zone_id is None:
            return None
        return next((z.name for z in camera.zones if z.id == zone_id), None)

    def event_view(self, event: Event) -> dict:
        camera = self.cameras.get(event.camera_id)
        view = to_json(event)
        view.update(
            camera_name=camera.name if camera else None,
            title=self.titles.get(event.type, event.type),
            zone_name=self.zone_name(event.camera_id, event.zone_id),
            status=self.status.get(event.id, "new"),
            comment=self.comment.get(event.id),
            snapshot_url=f"/media/{event.camera_id}/{event.id}.jpg",
            clip_url=None,
        )
        return view


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
