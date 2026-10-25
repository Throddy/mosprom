"""Пайплайн: поток на камеру и DETECTOR_WORKERS потоков-обработчиков, каждый со своим детектором.

Камеры распределяются по обработчикам при старте по кругу в порядке конфига. Камера всегда обрабатывается
одним и тем же обработчиком: её Engine вызывается только из него, кадры идут строго по порядку.
Обработчик берёт последние кадры своих камер и вызывает infer одним списком.

Камеры из TILED_CAMERAS обрабатывают отдельные TILED_WORKERS обработчиков с детекторами
create_detector(<бэкенд>, tiles=True). Если бэкенд плитки не поддерживает (ValueError), эти камеры
переходят к обычным обработчикам.

Камера читает кадры с частотой показа max(fps камеры, STREAM_FPS). Детектор получает кадр камеры не чаще fps
камеры; правила и ts событий считаются только по этим кадрам.

Показ (/stream, /frame) идёт с задержкой D: кадры показа хранятся в буфере за последние STREAM_BUFFER_MAX с,
результаты детектора — по ts обработанного кадра. view() отдаёт кадр с ts ≈ now − D и треки, интерполированные
между результатами до и после этого кадра. D = p90 задержки обработки за 20 кадров + 1/fps + 0.2 с
(STREAM_DELAY=auto) или число секунд из STREAM_DELAY, не больше STREAM_BUFFER_MAX.
"""
import logging
import os
import threading
import time
from collections import deque

import numpy as np

from backend.sources import FrameSource, RtspSource, open_source
from backend.threads import limit_threads
from core.schemas import CameraConfig
from logic import Engine, Result

log = logging.getLogger(__name__)

REOPEN_DELAY = 5.0
FPS_WINDOW = 5.0
LATENCY_WINDOW = 10


def stream_fps() -> float:
    return float(os.environ.get("STREAM_FPS", "15"))


def stream_buffer_max() -> float:
    return float(os.environ.get("STREAM_BUFFER_MAX", "12"))


def stream_delay() -> float | None:
    """STREAM_DELAY: число секунд или None для auto."""
    value = os.environ.get("STREAM_DELAY", "auto").strip()
    return None if value in ("", "auto") else float(value)


RESULTS_KEEP = 30
DELAY_WINDOW = 20


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
        self.buffer: deque = deque()  # (ts, frame) кадров показа за последние секунды
        self.buffer_last = 0.0
        self.results: deque = deque(maxlen=RESULTS_KEEP)  # {"ts", "tracks"} по ts обработанного кадра
        self.delays: deque = deque(maxlen=DELAY_WINDOW)  # задержка обработки, с
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
        limit_threads()
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
                        self._buffer(cam, item)
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
                tracks = _track_views(result.tracks, cam.engine)
                # Люди из детекций, в том числе ещё без подтверждённого трека: для размытия
                people = [{"bbox": tuple(float(v) for v in d.bbox), "kpts": d.kpts}
                          for d in detections if d.cls == "person"]
                with cam.lock:
                    cam.results.append({"ts": ts, "tracks": tracks, "people": people})
                    cam.delays.append(done - ts)
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

    def _buffer(self, cam: _Camera, item: tuple) -> None:
        """Кадр в буфер показа не чаще STREAM_FPS; хранится не дольше D + 1 с и не больше STREAM_BUFFER_MAX."""
        ts = item[0]
        if ts - cam.buffer_last >= 0.9 / max(stream_fps(), 1.0):
            cam.buffer.append(item)
            cam.buffer_last = ts
        keep = min(stream_buffer_max(), self._delay(cam) + 1.0)
        while len(cam.buffer) > 1 and cam.buffer[0][0] < ts - keep:
            cam.buffer.popleft()

    def _delay(self, cam: _Camera) -> float:
        fixed = stream_delay()
        if fixed is not None:
            return min(max(fixed, 0.0), stream_buffer_max())
        period = 1.0 / cam.cfg.fps if cam.cfg.fps > 0 else 0.0
        p90 = float(np.percentile(list(cam.delays), 90)) if cam.delays else 0.0
        return min(p90 + period + 0.2, stream_buffer_max())

    def view(self, camera_id: str, now: float | None = None) -> dict | None:
        """Кадр показа с ts ≈ now − D и треки на этот ts. None, пока кадров нет.

        covered — есть результат детектора в пределах 2/fps от ts кадра; people — люди из детекций тех же
        результатов, для размытия."""
        cam = self.cams[camera_id]
        now = time.time() if now is None else now
        with cam.lock:
            if not cam.buffer:
                return None
            delay = self._delay(cam)
            frames = list(cam.buffer)
            results = list(cam.results)
            fps = cam.cfg.fps
        target = now - delay
        chosen = frames[0]
        for item in frames:
            if item[0] <= target:
                chosen = item
            else:
                break
        ts, frame = chosen
        period = 1.0 / fps if fps > 0 else 1.0
        tracks = interpolate(results, ts, period)
        # Одно окно 2/fps: кадр «покрыт», только если люди для размытия берутся из тех же результатов
        near = [r for r in results if abs(r["ts"] - ts) <= 2 * period]
        covered = bool(near)
        # Для размытия — люди из результатов до и после кадра в пределах 2/fps, включая неподтверждённые треки
        people = [p for r in near for p in r["people"]]
        return {"ts": ts, "frame": frame, "tracks": tracks, "people": people, "covered": covered, "delay": delay}

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
                "delay": self._delay(cam),
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


def _track_views(tracks, engine) -> list[dict]:
    """Треки результата для показа: бокс, точки из состояния трека движка, активные правила."""
    out = []
    for t in tracks:
        state = engine.tracks.get(t.track_id)
        kpts = getattr(state, "kpts", None)
        kpts = np.array(kpts, dtype=float) if isinstance(kpts, np.ndarray) and kpts.shape == (17, 3) else None
        out.append({"id": t.track_id, "cls": t.cls, "bbox": tuple(float(v) for v in t.bbox), "kpts": kpts,
                    "active": list(t.active)})
    return out


def _lerp(a: dict, b: dict, alpha: float) -> dict:
    bbox = tuple(x + (y - x) * alpha for x, y in zip(a["bbox"], b["bbox"]))
    kpts = None
    if a["kpts"] is not None and b["kpts"] is not None:
        kpts = a["kpts"].copy()
        kpts[:, :2] = a["kpts"][:, :2] + (b["kpts"][:, :2] - a["kpts"][:, :2]) * alpha
        kpts[:, 2] = np.minimum(a["kpts"][:, 2], b["kpts"][:, 2])
    else:
        kpts = (a if alpha < 0.5 else b)["kpts"]
    near = a if alpha < 0.5 else b
    return {"id": a["id"], "cls": a["cls"], "bbox": bbox, "kpts": kpts, "active": near["active"]}


def interpolate(results: list[dict], ts: float, period: float) -> list[dict]:
    """Треки на момент ts по двум результатам вокруг него.

    Трек из обоих результатов — линейная интерполяция бокса и точек по времени. Трек только из одного —
    берётся, если тот результат не дальше period от ts. Если результата после ts нет — последний результат,
    если он не старше period, иначе без треков."""
    prev = next_ = None
    for r in results:
        if r["ts"] <= ts:
            prev = r
        elif next_ is None or r["ts"] < next_["ts"]:
            next_ = r
    if prev is not None and next_ is not None:
        span = next_["ts"] - prev["ts"]
        alpha = (ts - prev["ts"]) / span if span > 0 else 0.0
        a = {t["id"]: t for t in prev["tracks"]}
        b = {t["id"]: t for t in next_["tracks"]}
        out = []
        for tid in dict.fromkeys(list(a) + list(b)):
            if tid in a and tid in b:
                out.append(_lerp(a[tid], b[tid], alpha))
            elif tid in a and ts - prev["ts"] <= period:
                out.append(a[tid])
            elif tid in b and next_["ts"] - ts <= period:
                out.append(b[tid])
        return out
    if prev is not None:
        return list(prev["tracks"]) if ts - prev["ts"] <= period else []
    if next_ is not None:
        return list(next_["tracks"]) if next_["ts"] - ts <= period else []
    return []
