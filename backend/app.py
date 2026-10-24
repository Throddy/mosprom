"""API бэкенда по CONTRACT.md, раздел 6. PIPELINE=1: реальные события из базы, PIPELINE=0: тестовые."""
import asyncio
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import snapshots
from backend.cameras import cameras_path, load_active, save_cameras
from backend.db import EventDB
from backend.draw import draw
from backend.fixtures import gray_frame, make_event, save_snapshot, seed_events
from backend.hub import STATUSES, Hub, Store, to_json
from backend.pipeline import Pipeline
from backend.validation import sanitize, validate_camera
from core.schemas import CameraConfig, Event, RuleConfig, Zone

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
MEDIA_DIR = ROOT / "backend" / "media"
DIST_DIR = ROOT / "frontend" / "dist"
DEFAULT_DB_PATH = "backend/data/events.sqlite3"


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
    comment: str | None = Field(None, max_length=1000)


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
    use_pipeline = os.environ.get("PIPELINE", "1") == "1"
    db = EventDB(os.environ.get("DB_PATH") or DEFAULT_DB_PATH) if use_pipeline else EventDB(":memory:")
    store = Store(load_active(), db)
    hub = Hub()
    cameras_lock = threading.Lock()
    interval = float(os.environ.get("FIXTURE_WS_INTERVAL", "10"))
    detector_backend = os.environ.get("DETECTOR_BACKEND") or "onnx"
    state = {"detector": None, "pipeline": None, "loop": None}
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    def add_fixture_event(event: Event) -> dict:
        save_snapshot(event, MEDIA_DIR)
        return store.add_event(event, f"{event.camera_id}/{event.id}.jpg")

    if not use_pipeline:
        # Тестовые события засеваются сразу, без lifespan: TestClient без with тоже их видит
        for seed in seed_events():
            add_fixture_event(seed)

    async def fixture_loop():
        while True:
            await asyncio.sleep(interval)
            view = add_fixture_event(make_event(time.time()))
            await hub.broadcast("event_new", view)

    def send(kind: str, view: dict) -> None:
        # on_result вызывается из потока детектора, рассылка идёт в цикле событий сервера
        loop = state["loop"]
        if loop is not None and view is not None:
            asyncio.run_coroutine_threadsafe(hub.broadcast(kind, view), loop)

    def on_result(camera_id, ts, frame, result):
        for event in result.new_events:
            # Сначала событие в базу и в WebSocket, снимок после: без снимка тревога не теряется.
            try:
                send("event_new", store.add_event(event, snapshots.snapshot_path(camera_id, event.id)))
                # От получения кадра до передачи event_new в цикл событий сервера
                log.info("alarm latency: camera %s type %s frame_to_ws_ms %.1f", camera_id, event.type,
                         (time.time() - ts) * 1000.0)
                log.info("event new: camera %s type %s track %s ts_confirm %.2f", camera_id, event.type,
                         event.track_id, event.ts_confirm)
            except Exception:
                log.exception("камера %s: событие %s не сохранено", camera_id, event.id)
                continue
            try:
                snapshots.save_snapshot(frame, event, camera_id)
            except Exception:
                log.error("камера %s: снимок события %s не записан", camera_id, event.id, exc_info=True)
        for event in result.closed_events:
            try:
                send("event_update", store.close_event(event.id, event.ts_end))
                log.info("event closed: camera %s type %s track %s ts_end %.2f", camera_id, event.type,
                         event.track_id, event.ts_end)
            except Exception:
                log.exception("камера %s: событие %s не закрыто", camera_id, event.id)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state["loop"] = asyncio.get_running_loop()
        task = None
        if use_pipeline:
            closed = db.close_open(time.time())
            log.info("закрыто открытых событий при старте: %d", closed)
            from ml import create_detector
            state["detector"] = create_detector()
            state["pipeline"] = Pipeline(list(store.cameras.values()), state["detector"], on_result)
            state["pipeline"].start()
        else:
            task = asyncio.create_task(fixture_loop())
        yield
        if task is not None:
            task.cancel()
        if state["pipeline"] is not None:
            state["pipeline"].stop()
        state["loop"] = None

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

    @app.get("/api/status")
    def status():
        pipeline = state["pipeline"]
        if pipeline is not None:
            cams = []
            for c in store.cameras.values():
                snap = pipeline.snapshot(c.id)
                cams.append({"id": c.id, "online": snap["online"], "fps": round(snap["fps"], 1),
                             "latency_ms": round(snap["latency_ms"], 1)})
            return {"detector": state["detector"].name, "backend": detector_backend, "cameras": cams}
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
    def put_camera(camera_id: str, body: dict = Body(...)):
        # Чтение, изменение и запись камер под одной блокировкой: одновременные PUT не теряют изменения
        with cameras_lock:
            get_camera(camera_id)
            if body.get("id") != camera_id:
                raise HTTPException(400, "id in path and body differ")
            errors = validate_camera(body, {r["type"]: r for r in store.rule_specs()})
            if errors:
                log.warning("камера %s: PUT отклонён: %s", sanitize(camera_id), sanitize("; ".join(errors)))
                raise HTTPException(422, "; ".join(errors))
            try:
                cfg = CameraIn(**body).to_config()
            except ValueError as e:
                raise HTTPException(422, sanitize(e))
            old = store.cameras[camera_id]
            store.cameras[camera_id] = cfg
            try:
                save_cameras(cameras_path(), list(store.cameras.values()))
            except Exception as e:
                store.cameras[camera_id] = old
                log.error("камера %s: камеры не записаны: %s", camera_id, sanitize(e))
                raise HTTPException(500, "не удалось сохранить камеры")
            if state["pipeline"] is not None:
                state["pipeline"].update_camera(cfg)
            log.info("камера %s: изменения применены", camera_id)
            return to_json(cfg)

    @app.get("/api/cameras/{camera_id}/frame")
    def frame(camera_id: str):
        camera = get_camera(camera_id)
        pipeline = state["pipeline"]
        if pipeline is not None:
            img = pipeline.snapshot(camera_id)["frame"]
            if img is None:
                raise HTTPException(503, "кадра ещё нет")
            return Response(encode_jpeg(img), media_type="image/jpeg")
        return Response(encode_jpeg(camera_frame(camera)), media_type="image/jpeg")

    async def pipeline_frames(pipeline: Pipeline, camera_id: str):
        last_ts = None
        while True:
            camera = store.cameras.get(camera_id)
            if camera is None:
                return
            snap = pipeline.snapshot(camera_id)
            if snap["frame"] is not None and snap["ts"] != last_ts:
                last_ts = snap["ts"]
                info = f"{camera_id} fps {snap['fps']:.1f} lat {snap['latency_ms']:.0f} ms"
                jpeg = encode_jpeg(draw(snap["frame"], snap["detections"], camera.zones, info, snap["tracks"]))
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                await asyncio.sleep(1.0 / camera.fps if camera.fps > 0 else 0.1)
            else:
                await asyncio.sleep(0.02)

    @app.get("/api/cameras/{camera_id}/stream")
    async def stream(camera_id: str):
        get_camera(camera_id)
        if state["pipeline"] is not None:
            return StreamingResponse(pipeline_frames(state["pipeline"], camera_id),
                                     media_type="multipart/x-mixed-replace; boundary=frame")

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
        return store.rule_specs()

    @app.get("/api/events")
    def events(
        type: str | None = None,
        camera_id: str | None = None,
        zone_id: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        ts_from: float | None = Query(None, alias="from"),
        ts_to: float | None = Query(None, alias="to"),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        items, total = store.list_events(type=type, camera_id=camera_id, zone_id=zone_id, status=status,
                                         severity=severity, ts_from=ts_from, ts_to=ts_to,
                                         limit=limit, offset=offset)
        return {"items": items, "total": total}

    @app.patch("/api/events/{event_id}")
    async def patch_event(event_id: str, body: EventPatch):
        if body.status not in STATUSES:
            raise HTTPException(400, f"unknown status {body.status}")
        view = store.set_status(event_id, body.status, body.comment)
        if view is None:
            raise HTTPException(404, f"event {event_id} not found")
        await hub.broadcast("event_update", view)
        return view

    @app.get("/api/stats")
    def stats(
        ts_from: float | None = Query(None, alias="from"),
        ts_to: float | None = Query(None, alias="to"),
    ):
        return store.stats(ts_from, ts_to)

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
