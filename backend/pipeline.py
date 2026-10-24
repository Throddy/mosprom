"""Пайплайн: поток на камеру и общий поток детектора, который берёт последний кадр каждой камеры.

Камера читает кадры с частотой показа max(fps камеры, STREAM_FPS): последний кадр идёт в /stream.
Детектор получает кадр камеры не чаще fps камеры; правила и ts событий считаются только по этим кадрам.
"""
import logging
import os
import threading
import time
from collections import deque

from backend.sources import FrameSource, RtspSource, open_source
from core.schemas import CameraConfig
from logic import Engine, Result

log = logging.getLogger(__name__)

REOPEN_DELAY = 5.0
FPS_WINDOW = 5.0
LATENCY_WINDOW = 10


def stream_fps() -> float:
    return float(os.environ.get("STREAM_FPS", "15"))


class _Camera:
    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.slot = None  # (ts, frame), ещё не обработанный детектором
        self.next_due = 0.0  # ts, с которого следующий кадр идёт детектору
        self.display = None  # (ts, frame), последний прочитанный кадр для показа
        self.online = False
        self.frame = None
        self.detections = []
        self.tracks = []
        self.ts = None
        self.engine = Engine(cfg)
        self.processed = deque()  # время обработки кадров за последние FPS_WINDOW с
        self.latencies = deque(maxlen=LATENCY_WINDOW)
        self.reopen = threading.Event()
        self.source: FrameSource | None = None
        self.thread: threading.Thread | None = None

    def interrupt(self) -> None:
        # read() у RTSP ждёт кадр без ограничения времени, close() его прерывает.
        source = self.source
        if isinstance(source, RtspSource):
            source.close()


class Pipeline:
    def __init__(self, cameras: list[CameraConfig], detector, on_result=None):
        self.detector = detector
        self.on_result = on_result
        self.cams = {c.id: _Camera(c) for c in cameras}
        self.stopped = threading.Event()
        self.detector_thread: threading.Thread | None = None

    def start(self) -> None:
        self.stopped.clear()
        for cam in self.cams.values():
            self._start_camera(cam)
        self.detector_thread = threading.Thread(target=self._detector_loop, name="detector", daemon=True)
        self.detector_thread.start()

    def stop(self) -> None:
        self.stopped.set()
        for cam in self.cams.values():
            cam.interrupt()
        deadline = time.monotonic() + 3.0
        threads = [c.thread for c in self.cams.values()] + [self.detector_thread]
        for t in threads:
            if t is not None:
                t.join(timeout=max(0.0, deadline - time.monotonic()))

    def _start_camera(self, cam: _Camera) -> None:
        cam.thread = threading.Thread(target=self._camera_loop, args=(cam,), name=f"cam-{cam.cfg.id}",
                                      daemon=True)
        cam.thread.start()

    def _camera_loop(self, cam: _Camera) -> None:
        while not self.stopped.is_set():
            cam.reopen.clear()
            source: FrameSource | None = None
            try:
                read_fps = max(cam.cfg.fps, stream_fps())
                source = cam.source = open_source(cam.cfg.source, read_fps)
                while not self.stopped.is_set() and not cam.reopen.is_set():
                    item = source.read()
                    if item is None:
                        break
                    with cam.lock:
                        cam.display = item
                        cam.online = True
                        # Детектору — не чаще fps камеры: следующий срок сдвигается на период камеры
                        period = 1.0 / cam.cfg.fps if cam.cfg.fps > 0 else 0.0
                        if item[0] >= cam.next_due - 1e-6:
                            cam.slot = item
                            cam.next_due = max(cam.next_due + period, item[0] - period)
            except Exception:
                log.exception("камера %s: ошибка источника", cam.cfg.id)
            finally:
                cam.source = None
                if source is not None:
                    source.close()
            if self.stopped.is_set():
                break
            if cam.reopen.is_set():
                continue
            with cam.lock:
                cam.online = False
            self.stopped.wait(REOPEN_DELAY)

    def _detector_loop(self) -> None:
        while not self.stopped.is_set():
            batch = []
            for cam in self.cams.values():
                with cam.lock:
                    item, cam.slot = cam.slot, None
                if item is not None:
                    batch.append((cam, item[0], item[1]))
            if not batch:
                self.stopped.wait(0.005)
                continue
            try:
                results = self.detector.infer([frame for _, _, frame in batch])
            except Exception:
                log.exception("ошибка детектора")
                self.stopped.wait(1.0)
                continue
            for (cam, ts, frame), detections in zip(batch, results):
                h, w = frame.shape[:2]
                try:
                    result = cam.engine.process(ts, w, h, detections)
                except Exception:
                    log.exception("камера %s: ошибка движка правил", cam.cfg.id)
                    result = Result()
                done = time.time()
                # Время конца обработки кадра для замера задержки до тревоги (BE-10)
                result.t_done = done
                with cam.lock:
                    cam.frame = frame
                    cam.detections = detections
                    cam.tracks = result.tracks
                    cam.ts = ts
                    cam.processed.append(done)
                    while cam.processed and cam.processed[0] < done - FPS_WINDOW:
                        cam.processed.popleft()
                    cam.latencies.append((done - ts) * 1000.0)
                if self.on_result is not None:
                    try:
                        self.on_result(cam.cfg.id, ts, frame, result)
                    except Exception:
                        log.exception("камера %s: ошибка on_result", cam.cfg.id)

    def snapshot(self, camera_id: str) -> dict:
        cam = self.cams[camera_id]
        now = time.time()
        with cam.lock:
            processed = sum(1 for t in cam.processed if t >= now - FPS_WINDOW)
            latency = sum(cam.latencies) / len(cam.latencies) if cam.latencies else 0.0
            return {
                "online": cam.online,
                "fps": processed / FPS_WINDOW,
                "latency_ms": latency,
                "frame": cam.frame,
                "detections": cam.detections,
                "tracks": cam.tracks,
                "ts": cam.ts,
                "display": cam.display[1] if cam.display else None,
                "display_ts": cam.display[0] if cam.display else None,
            }

    def update_camera(self, cfg: CameraConfig) -> None:
        cam = self.cams.get(cfg.id)
        if cam is None:
            cam = _Camera(cfg)
            self.cams[cfg.id] = cam
            if self.detector_thread is not None and not self.stopped.is_set():
                self._start_camera(cam)
            return
        old = cam.cfg
        cam.cfg = cfg
        cam.engine.update_config(cfg)
        if old.source != cfg.source or old.fps != cfg.fps:
            cam.reopen.set()
            cam.interrupt()
