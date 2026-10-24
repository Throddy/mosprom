"""Пайплайн: поток на камеру и DETECTOR_WORKERS потоков-обработчиков, каждый со своим детектором.

Камеры распределяются по обработчикам при старте по кругу в порядке конфига. Камера всегда обрабатывается
одним и тем же обработчиком: её Engine вызывается только из него, кадры идут строго по порядку.
Обработчик берёт последние кадры своих камер и вызывает infer одним списком.

Камеры из TILED_CAMERAS обрабатывают отдельные TILED_WORKERS обработчиков с детекторами
create_detector(<бэкенд>, tiles=True). Если бэкенд плитки не поддерживает (ValueError), эти камеры
переходят к обычным обработчикам.

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


def _workers(name: str) -> int:
    return max(1, int(os.environ.get(name, "1")))


def detector_workers() -> int:
    return _workers("DETECTOR_WORKERS")


def tiled_workers() -> int:
    return _workers("TILED_WORKERS")


def tiled_cameras() -> list[str]:
    """Точные id из TILED_CAMERAS: пробелы вокруг id убираются, повторы удаляются."""
    ids = [x.strip() for x in os.environ.get("TILED_CAMERAS", "").split(",")]
    return list(dict.fromkeys(x for x in ids if x))


def _split(cams: list, n: int) -> list[list]:
    """По кругу в порядке конфига; обработчиков не больше, чем камер, для пустого списка — ни одного."""
    n = min(n, len(cams))
    return [cams[i::n] for i in range(n)]


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
    def __init__(self, cameras: list[CameraConfig], detector, on_result=None, factory=None):
        self.detector = detector
        self.on_result = on_result
        # Фабрика детекторов create_detector(backend, tiles=...); подменяется в проверках
        self.factory = factory
        self.cams = {c.id: _Camera(c) for c in cameras}
        self.stopped = threading.Event()
        self.detector_threads: list[threading.Thread] = []
        self.workers: list[dict] = []  # {"name", "tiles", "cameras"} для лога и проверок

    def _create(self, tiles: bool | None = None):
        factory = self.factory
        if factory is None:
            from ml import create_detector as factory
        backend = os.environ.get("DETECTOR_BACKEND", "onnx")
        return factory(backend, tiles=True) if tiles else factory(backend)

    def _tiled_detectors(self, tiled: list[_Camera]) -> list | None:
        """Детекторы с плитками для групп tiled, созданные до запуска потоков. None — бэкенд их не поддерживает."""
        detectors = []
        for _ in _split(tiled, tiled_workers()):
            try:
                detectors.append(self._create(tiles=True))
            except ValueError as e:
                log.warning("плитки недоступны (%s): камеры %s обрабатываются без плиток", e,
                            ", ".join(c.cfg.id for c in tiled))
                return None
        return detectors

    def start(self) -> None:
        self.stopped.clear()
        wanted = tiled_cameras()
        for camera_id in wanted:
            if camera_id not in self.cams:
                log.warning("TILED_CAMERAS: камеры %s нет, пропущена", camera_id)
        tiled = [c for c in self.cams.values() if c.cfg.id in wanted]
        tiled_detectors = self._tiled_detectors(tiled) if tiled else []
        if tiled_detectors is None:
            tiled, tiled_detectors = [], []
        normal = [c for c in self.cams.values() if c not in tiled]

        # (камеры, готовый детектор или None — создать в потоке, плитки)
        plan = [(group, self.detector if i == 0 else None, False)
                for i, group in enumerate(_split(normal, detector_workers()))]
        plan += [(group, det, True) for group, det in zip(_split(tiled, tiled_workers()), tiled_detectors)]
        if not plan:
            plan = [([], self.detector, False)]

        for cam in self.cams.values():
            self._start_camera(cam)
        self.workers = []
        self.detector_threads = []
        for i, (group, detector, tiles) in enumerate(plan):
            name = f"detector-{i}" + ("-tiles" if tiles else "")
            self.workers.append({"name": name, "tiles": tiles, "cameras": [c.cfg.id for c in group]})
            log.info("обработчик %s: камеры %s, плитки %s", name, ", ".join(c.cfg.id for c in group) or "-",
                     "да" if tiles else "нет")
            self.detector_threads.append(threading.Thread(
                target=self._detector_loop, args=(group, detector), name=name, daemon=True))
        for t in self.detector_threads:
            t.start()

    @property
    def detector_thread(self) -> threading.Thread | None:
        # Для проверок: живой обработчик, если есть, иначе первый
        alive = [t for t in self.detector_threads if t.is_alive()]
        return (alive or self.detector_threads or [None])[0]

    def stop(self) -> None:
        self.stopped.set()
        for cam in self.cams.values():
            cam.interrupt()
        deadline = time.monotonic() + 3.0
        threads = [c.thread for c in self.cams.values()] + self.detector_threads
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

    def _detector_loop(self, cams: list[_Camera], detector) -> None:
        if detector is None:
            # Детектор может быть непотокобезопасным (CONTRACT.md, раздел 4): у обработчика свой экземпляр,
            # созданный в его потоке
            try:
                detector = self._create()
            except Exception:
                log.exception("обработчик %s: детектор не создан", threading.current_thread().name)
                return
        while not self.stopped.is_set():
            batch = []
            for cam in cams:
                with cam.lock:
                    item, cam.slot = cam.slot, None
                if item is not None:
                    batch.append((cam, item[0], item[1]))
            if not batch:
                self.stopped.wait(0.005)
                continue
            try:
                results = detector.infer([frame for _, _, frame in batch])
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
            # Камеры закреплены за обработчиками при старте; API меняет только существующие камеры
            log.warning("камера %s: нет в пайплайне, изменения не применены", cfg.id)
            return
        old = cam.cfg
        cam.cfg = cfg
        cam.engine.update_config(cfg)
        if old.source != cfg.source or old.fps != cfg.fps:
            cam.reopen.set()
            cam.interrupt()
