"""API бэкенда по CONTRACT.md, раздел 6. До BE-6 работает на тестовых данных."""
import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.fixtures import CAMERAS, RULES, gray_frame, make_event, save_snapshot, seed_events
from backend.hub import Hub, Store, to_json
from core.schemas import SEVERITIES, CameraConfig, RuleConfig, Zone

ROOT = Path(__file__).resolve().parent.parent
MEDIA_DIR = ROOT / "backend" / "media"
DIST_DIR = ROOT / "frontend" / "dist"
STATUSES = ("new", "confirmed", "false", "forwarded")


class ZoneIn(BaseModel):
    id: str
    name: str
    polygon: list[tuple[float, float]]


class RuleIn(BaseModel):
    type: str
    enabled: bool = True
    zone: str | None = None
    schedule: tuple[str, str] | None = None
    params: dict = {}


class CameraIn(BaseModel):
    id: str
    name: str
    source: str
    fps: float
    zones: list[ZoneIn] = []
    rules: list[RuleIn] = []

    def to_config(self) -> CameraConfig:
        return CameraConfig(
            id=self.id, name=self.name, source=self.source, fps=self.fps,
            zones=[Zone(**z.model_dump()) for z in self.zones],
            rules=[RuleConfig(**r.model_dump()) for r in self.rules],
        )


class EventPatch(BaseModel):
    status: str
    comment: str | None = None


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def camera_frame(camera: CameraConfig, with_zones: bool = False) -> np.ndarray:
    img = gray_frame()
    text = f"{camera.name} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    cv2.putText(img, text, (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    if with_zones:
        h, w = img.shape[:2]
        for zone in camera.zones:
            pts = np.array([[x * w, y * h] for x, y in zone.polygon], np.int32)
            cv2.polylines(img, [pts], True, (0, 255, 255), 3)
    return img


def encode_jpeg(img: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", img)[1].tobytes()


def create_app() -> FastAPI:
    store = Store(CAMERAS, seed_events())
    hub = Hub()
    interval = float(os.environ.get("FIXTURE_WS_INTERVAL", "10"))
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    def add_event(event):
        save_snapshot(event, store.cameras[event.camera_id].name, MEDIA_DIR)
        store.add_event(event)

    async def fixture_loop():
        while True:
            await asyncio.sleep(interval)
            event = make_event(time.time())
            add_event(event)
            await hub.broadcast("event_new", store.event_view(event))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for event in store.events.values():
            save_snapshot(event, store.cameras[event.camera_id].name, MEDIA_DIR)
        task = asyncio.create_task(fixture_loop())
        yield
        task.cancel()

    app = FastAPI(lifespan=lifespan)
    app.state.store = store
    app.state.hub = hub
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        detail = errors[0]["msg"] if errors else "invalid request"
        return JSONResponse(status_code=422, content={"detail": detail})

    def get_camera(camera_id: str) -> CameraConfig:
        camera = store.cameras.get(camera_id)
        if camera is None:
            raise HTTPException(404, f"camera {camera_id} not found")
        return camera

    def filter_by_ts(events, ts_from, ts_to):
        if ts_from is not None:
            events = [e for e in events if e.ts_confirm >= ts_from]
        if ts_to is not None:
            events = [e for e in events if e.ts_confirm <= ts_to]
        return events

    @app.get("/api/status")
    def status():
        return {
            "detector": "fixtures",
            "backend": "fixtures",
            "cameras": [{"id": c.id, "online": True, "fps": 10.0, "latency_ms": 0.0}
                        for c in store.cameras.values()],
        }

    @app.get("/api/cameras")
    def cameras():
        return [to_json(c) for c in store.cameras.values()]

    @app.put("/api/cameras/{camera_id}")
    def put_camera(camera_id: str, body: CameraIn):
        if body.id != camera_id:
            raise HTTPException(400, "id in path and body differ")
        get_camera(camera_id)
        store.cameras[camera_id] = body.to_config()
        return to_json(store.cameras[camera_id])

    @app.get("/api/cameras/{camera_id}/frame")
    def frame(camera_id: str):
        camera = get_camera(camera_id)
        return Response(encode_jpeg(camera_frame(camera)), media_type="image/jpeg")

    @app.get("/api/cameras/{camera_id}/stream")
    async def stream(camera_id: str):
        get_camera(camera_id)

        async def frames():
            while True:
                camera = store.cameras.get(camera_id)
                if camera is None:
                    return
                jpeg = encode_jpeg(camera_frame(camera, with_zones=True))
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/rules")
    def rules():
        return RULES

    @app.get("/api/events")
    def events(
        type: str | None = None,
        camera_id: str | None = None,
        zone_id: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        ts_from: float | None = Query(None, alias="from"),
        ts_to: float | None = Query(None, alias="to"),
        limit: int = 50,
        offset: int = 0,
    ):
        items = filter_by_ts(list(store.events.values()), ts_from, ts_to)
        if type is not None:
            items = [e for e in items if e.type == type]
        if camera_id is not None:
            items = [e for e in items if e.camera_id == camera_id]
        if zone_id is not None:
            items = [e for e in items if e.zone_id == zone_id]
        if status is not None:
            items = [e for e in items if store.status.get(e.id, "new") == status]
        if severity is not None:
            items = [e for e in items if e.severity == severity]
        items.sort(key=lambda e: e.ts_confirm, reverse=True)
        page = items[offset:offset + limit]
        return {"items": [store.event_view(e) for e in page], "total": len(items)}

    @app.patch("/api/events/{event_id}")
    async def patch_event(event_id: str, body: EventPatch):
        if body.status not in STATUSES:
            raise HTTPException(400, f"unknown status {body.status}")
        event = store.events.get(event_id)
        if event is None:
            raise HTTPException(404, f"event {event_id} not found")
        store.status[event_id] = body.status
        store.comment[event_id] = body.comment
        view = store.event_view(event)
        await hub.broadcast("event_update", view)
        return view

    @app.get("/api/stats")
    def stats(
        ts_from: float | None = Query(None, alias="from"),
        ts_to: float | None = Query(None, alias="to"),
    ):
        items = filter_by_ts(list(store.events.values()), ts_from, ts_to)
        result = {
            "total": len(items),
            "by_type": {r["type"]: 0 for r in RULES},
            "by_camera": {c: 0 for c in store.cameras},
            "by_severity": {s: 0 for s in SEVERITIES},
            "by_status": {s: 0 for s in STATUSES},
            "by_hour": [0] * 24,
            "by_day": {},
        }
        for e in items:
            dt = datetime.fromtimestamp(e.ts_confirm)
            day = dt.strftime("%Y-%m-%d")
            st = store.status.get(e.id, "new")
            result["by_type"][e.type] = result["by_type"].get(e.type, 0) + 1
            result["by_camera"][e.camera_id] = result["by_camera"].get(e.camera_id, 0) + 1
            result["by_severity"][e.severity] = result["by_severity"].get(e.severity, 0) + 1
            result["by_status"][st] = result["by_status"].get(st, 0) + 1
            result["by_hour"][dt.hour] += 1
            result["by_day"][day] = result["by_day"].get(day, 0) + 1
        result["by_day"] = dict(sorted(result["by_day"].items()))
        return result

    @app.get("/api/benchmarks")
    def benchmarks():
        return read_json(ROOT / "reports" / "benchmarks.json", [])

    @app.get("/api/metrics")
    def metrics():
        return read_json(ROOT / "reports" / "metrics.json", {})

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket):
        await ws.accept()
        hub.add(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.remove(ws)

    app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
    if (DIST_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="frontend")

    return app
