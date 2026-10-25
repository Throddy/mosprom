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
from backend.draw import draw_tracks
from backend.fixtures import gray_frame, make_event, save_snapshot, seed_events
from backend.hub import STATUSES, Hub, Store, to_json
from backend.pipeline import Pipeline, stream_fps, tiled_cameras
from backend.privacy import blur_enabled, blur_people, blur_top
from backend.hls import HlsWriter, hls_dir, hls_enabled
from backend.threads import limit_threads
from backend.validation import sanitize, validate_camera
from core.schemas import CameraConfig, Detection, Event, RuleConfig, Zone

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


def encode_jpeg(img: np.ndarray, quality: int | None = None) -> bytes:
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if quality else []
    return cv2.imencode(".jpg", img, params)[1].tobytes()


def stream_width() -> int:
    """STREAM_WIDTH: ширина кадра /stream; 0 — исходная."""
    return int(os.environ.get("STREAM_WIDTH", "0") or 0)


def stream_quality() -> int:
    return int(os.environ.get("STREAM_QUALITY", "85"))


def privacy_view(camera_id: str, frame: np.ndarray, tracks: list[dict], people: list[dict],
                 covered: bool) -> np.ndarray:
    """Размытие голов по трекам кадра показа и по людям из соседних результатов детектора (новый человек
    ещё без подтверждённого трека). Камера трансляции без результатов детектора рядом с кадром — размытие
    верхних 40 % кадра целиком."""
    if not blur_enabled():
        return frame
    heads = [Detection(cls="person", conf=1.0, bbox=t["bbox"], kpts=t["kpts"]) for t in tracks if t["cls"] == "person"]
    heads += [Detection(cls="person", conf=1.0, bbox=p["bbox"], kpts=p["kpts"]) for p in people]
    img = blur_people(frame, heads)
    if not covered and (camera_id in tiled_cameras() or camera_id.startswith("live_")):
        img = blur_top(img, 0.4)
    return img


def scale_view(frame: np.ndarray, items: list[list[dict]], width: int) -> tuple[np.ndarray, list[list[dict]]]:
    """Кадр и списки боксов с точками, уменьшенные до ширины width с сохранением пропорций."""
    h, w = frame.shape[:2]
    if width <= 0 or w <= width:
        return frame, items
    k = width / w
    img = cv2.resize(frame, (width, max(int(round(h * k)), 1)), interpolation=cv2.INTER_AREA)
    out = []
    for group in items:
        scaled = []
        for t in group:
            kpts = t["kpts"]
            if isinstance(kpts, np.ndarray):
                kpts = kpts.copy()
                kpts[:, :2] *= k
            scaled.append({**t, "bbox": tuple(v * k for v in t["bbox"]), "kpts": kpts})
        out.append(scaled)
    return img, out


class HlsFiles(StaticFiles):
    """Статика HLS: плейлист без кэша, сегменты на 60 с."""

    def file_response(self, full_path, *args, **kwargs):
        response = super().file_response(full_path, *args, **kwargs)
        response.headers["Cache-Control"] = "no-cache" if str(full_path).endswith(".m3u8") else "max-age=60"
        return response


def create_app() -> FastAPI:
    use_pipeline = os.environ.get("PIPELINE", "1") == "1"
    db = EventDB(os.environ.get("DB_PATH") or DEFAULT_DB_PATH) if use_pipeline else EventDB(":memory:")
    store = Store(load_active(), db)
    hub = Hub()
    cameras_lock = threading.Lock()
    # Демо-стенд: только просмотр и лимит одновременных MJPEG-потоков
    read_only = os.environ.get("READ_ONLY", "0") == "1"
    max_streams = int(os.environ.get("MAX_STREAMS", "30"))
    streams = {"open": 0}
    streams_lock = threading.Lock()
    # Общий MJPEG: на камеру одна задача рисует и сжимает кадр, все зрители получают те же байты
    feeds: dict[str, dict] = {}
    mjpeg = {"encodes": {}}

    admin_local = os.environ.get("ADMIN_LOCAL", "0") == "1"

    def check_writable(request: Request) -> None:
        """READ_ONLY: изменения запрещены. ADMIN_LOCAL=1 разрешает их запросам через SSH-туннель:
        клиент 127.0.0.1 или ::1 и нет заголовков прокси (Caddy всегда добавляет X-Forwarded-For)."""
        if not read_only:
            return
        host = request.client.host if request.client else ""
        proxied = any(h in request.headers for h in ("x-forwarded-for", "x-real-ip", "forwarded"))
        if admin_local and host in ("127.0.0.1", "::1") and not proxied:
            log.info("%s %s: admin local", request.method, sanitize(request.url.path))
            return
        raise HTTPException(403, "Демо-стенд: только просмотр")
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
                detections = state["pipeline"].snapshot(camera_id)["detections"] if state["pipeline"] else None
                snapshots.save_snapshot(frame, event, camera_id, detections)
            except Exception:
                log.error("камера %s: снимок события %s не записан", camera_id, event.id, exc_info=True)
        for event in result.closed_events:
            try:
                send("event_update", store.close_event(event.id, event.ts_end))
                log.info("event closed: camera %s type %s track %s ts_end %.2f", camera_id, event.type,
                         event.track_id, event.ts_end)
            except Exception:
                log.exception("камера %s: событие %s не закрыто", camera_id, event.id)

    keep_minutes = float(os.environ.get("EVENTS_KEEP_MINUTES", "0") or 0)

    def cleanup_events(now: float) -> int:
        """Закрытые события с ts_confirm старше now − EVENTS_KEEP_MINUTES и их снимки."""
        snapshots_rel = db.delete_closed_before(now - keep_minutes * 60.0)
        for rel in snapshots_rel:
            path = (MEDIA_DIR / rel).resolve()
            if MEDIA_DIR.resolve() in path.parents:
                path.unlink(missing_ok=True)
        return len(snapshots_rel)

    async def cleanup_loop() -> None:
        """Раз в 60 с удаляет старые закрытые события; в лог не чаще раза в 5 минут."""
        removed, logged_at = 0, time.monotonic()
        while True:
            try:
                removed += await asyncio.to_thread(cleanup_events, time.time())
            except Exception:
                log.exception("очистка старых событий")
            if removed and time.monotonic() - logged_at >= 300:
                log.info("удалено старых событий: %d за %.0f мин", removed, (time.monotonic() - logged_at) / 60)
                removed, logged_at = 0, time.monotonic()
            await asyncio.sleep(60)

    hls_stop = threading.Event()
    hls_threads: list[threading.Thread] = []

    def hls_loop(pipeline: Pipeline, camera_id: str) -> None:
        """HLS камеры: кадр показа раз в 1/STREAM_FPS, независимо от зрителей. Если новый кадр показа
        не пришёл, повторяется прежний: ffmpeg получает кадры с постоянной частотой."""
        fps = max(stream_fps(), 1.0)
        period = 1.0 / fps
        writer = None
        last_ts, last_img = None, None
        next_at = time.monotonic()
        try:
            while not hls_stop.is_set():
                camera = store.cameras.get(camera_id)
                if camera is None:
                    break
                try:
                    view = pipeline.view(camera_id)
                    if view is not None and view["ts"] != last_ts:
                        last_ts = view["ts"]
                        last_img = show_frame(camera_id, camera, view, pipeline.snapshot(camera_id))
                    if last_img is not None:
                        if writer is None:
                            h, w = last_img.shape[:2]
                            writer = HlsWriter(camera_id, w, h, fps, hls_dir() / camera_id)
                        writer.write(last_img)
                except Exception:
                    log.exception("hls %s: ошибка кадра", camera_id)
                next_at = max(next_at + period, time.monotonic() - period)
                hls_stop.wait(max(0.0, next_at - time.monotonic()))
        finally:
            if writer is not None:
                writer.close()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state["loop"] = asyncio.get_running_loop()
        task = None
        if use_pipeline:
            closed = db.close_open(time.time())
            log.info("закрыто открытых событий при старте: %d", closed)
            from ml import create_detector
            # Потоки ONNX Runtime, PyTorch, OpenCV ограничиваются до создания детекторов (backend/threads.py)
            limit_threads()
            state["detector"] = create_detector()
            state["pipeline"] = Pipeline(list(store.cameras.values()), state["detector"], on_result)
            state["pipeline"].start()
            if hls_enabled():
                for camera_id in store.cameras:
                    t = threading.Thread(target=hls_loop, args=(state["pipeline"], camera_id),
                                         name=f"hls-{camera_id}", daemon=True)
                    hls_threads.append(t)
                    t.start()
        else:
            task = asyncio.create_task(fixture_loop())
        cleanup = asyncio.create_task(cleanup_loop()) if keep_minutes > 0 else None
        yield
        if cleanup is not None:
            cleanup.cancel()
        if task is not None:
            task.cancel()
        hls_stop.set()
        for t in hls_threads:
            t.join(timeout=5)
        if state["pipeline"] is not None:
            state["pipeline"].stop()
        state["loop"] = None

    app = FastAPI(lifespan=lifespan)
    app.state.store = store
    app.state.hub = hub
    app.state.mjpeg = mjpeg
    app.state.pipeline_state = state
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
    def put_camera(camera_id: str, request: Request, body: dict = Body(...)):
        check_writable(request)
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
    def frame(camera_id: str, w: int | None = Query(None, ge=160, le=1920)):
        camera = get_camera(camera_id)
        pipeline = state["pipeline"]
        if pipeline is not None:
            # Тот же кадр, что в /stream, с размытием и без разметки
            view = pipeline.view(camera_id)
            if view is None:
                raise HTTPException(503, "кадра ещё нет")
            img = privacy_view(camera_id, view["frame"], view["tracks"], view["people"], view["covered"])
        else:
            img = camera_frame(camera)
        if w is None:
            return Response(encode_jpeg(img), media_type="image/jpeg")
        # Лёгкое превью: ширина w с сохранением пропорций, JPEG 70
        h0, w0 = img.shape[:2]
        if w0 != w:
            img = cv2.resize(img, (w, max(int(round(h0 * w / w0)), 1)),
                             interpolation=cv2.INTER_AREA if w < w0 else cv2.INTER_LINEAR)
        return Response(encode_jpeg(img, 70), media_type="image/jpeg")

    def show_frame(camera_id: str, camera: CameraConfig, view: dict, snap: dict) -> np.ndarray:
        """Кадр показа с треками на его ts (Pipeline.view): ширина STREAM_WIDTH, размытие, разметка.
        Один и тот же для MJPEG и HLS."""
        info = f"{camera_id} fps {snap['fps']:.1f} lat {snap['latency_ms']:.0f} ms delay {view['delay']:.1f} s"
        img, (tracks, people) = scale_view(view["frame"], [view["tracks"], view["people"]], stream_width())
        # Размытие голов до рисования разметки и до сжатия
        img = privacy_view(camera_id, img, tracks, people, view["covered"])
        return draw_tracks(img, tracks, camera.zones, info)

    def render(camera_id: str, camera: CameraConfig, view: dict, snap: dict) -> bytes:
        """JPEG кадра показа, один на всех зрителей MJPEG."""
        jpeg = encode_jpeg(show_frame(camera_id, camera, view, snap), stream_quality())
        mjpeg["encodes"][camera_id] = mjpeg["encodes"].get(camera_id, 0) + 1
        return jpeg

    async def produce(pipeline: Pipeline, camera_id: str, feed: dict) -> None:
        """Пока есть зрители, раз в 1/STREAM_FPS с рисует и сжимает новый кадр камеры."""
        period = 1.0 / max(stream_fps(), 1.0)
        last_ts = None
        while feed["clients"] > 0:
            camera = store.cameras.get(camera_id)
            if camera is None:
                break
            view = pipeline.view(camera_id)
            if view is not None and view["ts"] != last_ts:
                last_ts = view["ts"]
                jpeg = await asyncio.to_thread(render, camera_id, camera, view, pipeline.snapshot(camera_id))
                async with feed["cond"]:
                    feed["jpeg"] = jpeg
                    feed["seq"] += 1
                    feed["cond"].notify_all()
            await asyncio.sleep(period)
        feed["task"] = None

    async def pipeline_frames(pipeline: Pipeline, camera_id: str):
        feed = feeds.setdefault(camera_id, {"jpeg": None, "seq": 0, "clients": 0, "task": None,
                                            "cond": asyncio.Condition()})
        feed["clients"] += 1
        if feed["task"] is None:
            feed["task"] = asyncio.create_task(produce(pipeline, camera_id, feed))
        seen = 0  # номер последнего отданного кадра; 0 — кадров ещё не было
        try:
            while store.cameras.get(camera_id) is not None:
                async with feed["cond"]:
                    await feed["cond"].wait_for(lambda: feed["jpeg"] is not None and feed["seq"] != seen)
                    seen, jpeg = feed["seq"], feed["jpeg"]
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        finally:
            feed["clients"] -= 1

    async def limited(frames):
        """Поток MJPEG в счётчике открытых /stream; счётчик уменьшается, когда клиент закрыл соединение."""
        try:
            async for chunk in frames:
                yield chunk
        finally:
            with streams_lock:
                streams["open"] -= 1

    @app.get("/api/cameras/{camera_id}/stream")
    async def stream(camera_id: str):
        get_camera(camera_id)
        with streams_lock:
            if streams["open"] >= max_streams:
                raise HTTPException(503, "Слишком много зрителей, попробуйте позже")
            streams["open"] += 1
        if state["pipeline"] is not None:
            return StreamingResponse(limited(pipeline_frames(state["pipeline"], camera_id)),
                                     media_type="multipart/x-mixed-replace; boundary=frame")

        async def frames():
            while True:
                camera = store.cameras.get(camera_id)
                if camera is None:
                    return
                jpeg = encode_jpeg(camera_frame(camera, with_zones=True))
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(limited(frames()), media_type="multipart/x-mixed-replace; boundary=frame")

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
    async def patch_event(event_id: str, body: EventPatch, request: Request):
        check_writable(request)
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
    if hls_enabled():
        # /hls/<camera_id>/index.m3u8 и сегменты; на стенде их раздаёт Caddy напрямую
        hls_dir().mkdir(parents=True, exist_ok=True)
        app.mount("/hls", HlsFiles(directory=hls_dir()), name="hls")
    if (DIST_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="frontend")

    return app
