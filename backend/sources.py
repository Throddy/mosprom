"""Источники кадров: видеофайл, RTSP, HTTP(S) поток, страница YouTube или Ivideon, папка с кадрами."""
import logging
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from backend import ivideon
from backend.validation import sanitize

ROOT = Path(__file__).resolve().parent.parent
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
log = logging.getLogger(__name__)


def _loop() -> bool:
    return os.environ.get("SOURCE_LOOP", "1") != "0"


class FrameSource:
    def read(self) -> tuple[float, np.ndarray] | None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class _Pacer:
    """Ограничивает частоту read() значением fps."""

    def __init__(self, fps: float):
        self.period = 1.0 / fps if fps > 0 else 0.0
        self.next = time.monotonic()

    def wait(self) -> None:
        now = time.monotonic()
        if self.next > now:
            time.sleep(self.next - now)
        self.next = max(self.next + self.period, time.monotonic() - self.period)


class FileSource(FrameSource):
    """Видеофайл в темпе реального времени: лишние кадры пропускаются по частоте видео."""

    def __init__(self, path: Path, fps: float):
        self.path = path
        self.fps = fps
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise OSError(f"не открывается видео: {path}")
        self.video_fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.pacer = _Pacer(fps)
        self.pos = 0.0  # номер следующего кадра для выдачи, в кадрах видео
        self.index = 0  # номер следующего кадра в cap
        self.last_frame: np.ndarray | None = None

    def _grab_frame(self) -> np.ndarray | None:
        target = int(self.pos)
        if target < self.index and self.last_frame is not None:
            # Частота чтения выше частоты видео: повторить кадр, чтобы видео шло в реальном времени
            return self.last_frame
        while self.index < target:
            if not self.cap.grab():
                return None
            self.index += 1
        ok, frame = self.cap.read()
        if not ok:
            return None
        self.index += 1
        self.last_frame = frame
        return frame

    def read(self) -> tuple[float, np.ndarray] | None:
        self.pacer.wait()
        frame = self._grab_frame()
        if frame is None:
            if not _loop():
                return None
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.pos = 0.0
            self.index = 0
            self.last_frame = None
            frame = self._grab_frame()
            if frame is None:
                return None
        self.pos += self.video_fps / self.fps
        return time.time(), frame

    def close(self) -> None:
        self.cap.release()


class RtspSource(FrameSource):
    """RTSP: отдельный поток читает кадры и хранит только последний."""

    reconnect = 2.0  # пауза перед переподключением, с

    def __init__(self, url: str, fps: float):
        self.url = url
        self.pacer = _Pacer(fps)
        self.lock = threading.Lock()
        self.last: tuple[float, np.ndarray] | None = None
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _stream_url(self) -> str | None:
        return self.url

    def _run(self) -> None:
        while not self.stopped.is_set():
            url = self._stream_url()
            if url:
                cap = cv2.VideoCapture(url)
                while not self.stopped.is_set() and cap.isOpened():
                    ok, frame = cap.read()
                    if not ok:
                        break
                    with self.lock:
                        self.last = (time.time(), frame)
                cap.release()
            self.stopped.wait(self.reconnect)

    def read(self) -> tuple[float, np.ndarray] | None:
        self.pacer.wait()
        while not self.stopped.is_set():
            with self.lock:
                last, self.last = self.last, None
            if last is not None:
                return last
            self.stopped.wait(0.01)
        return None

    def close(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=3)


class HttpSource(RtspSource):
    """HTTP(S) поток, например HLS .m3u8: как RTSP, переподключение каждые 5 с.
    Для главного плейлиста HLS выбирается вариант до 720p."""

    reconnect = 5.0

    def _stream_url(self) -> str | None:
        if urllib.parse.urlsplit(self.url).path.endswith(".m3u8"):
            try:
                return hls_variant(self.url)
            except Exception as e:
                log.warning("источник %s: плейлист HLS не прочитан: %s", sanitize(ivideon.safe(self.url)), sanitize(e))
                return self.url
        return self.url


def hls_variant(url: str, max_height: int = 720) -> str:
    """Для главного плейлиста HLS — вариант с наибольшей высотой не больше max_height, а если таких нет,
    с наименьшей высотой. Для плейлиста одного варианта — тот же адрес."""
    request = urllib.request.Request(url, headers={"User-Agent": ivideon.HEADERS["User-Agent"]})
    with urllib.request.urlopen(request, timeout=15, context=ivideon._context()) as r:
        text = r.read(65536).decode("utf-8", "replace")
    variants, height = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF"):
            m = re.search(r"RESOLUTION=(\d+)x(\d+)", line)
            height = int(m.group(2)) if m else 0
        elif line and not line.startswith("#") and height is not None:
            variants.append((height, urllib.parse.urljoin(url, line)))
            height = None
    if not variants:
        return url
    fit = [v for v in variants if 0 < v[0] <= max_height]
    return max(fit)[1] if fit else min(variants)[1]


class ResolvedSource(HttpSource):
    """Источник, у которого прямая ссылка на поток получается отдельным запросом.
    При обрыве ссылка получается заново, но не чаще раза в RESOLVE_EVERY секунд."""

    RESOLVE_EVERY = 60.0

    def __init__(self, page: str, fps: float):
        self.page = page
        self.direct: str | None = None
        self.resolved_at = 0.0
        self.warned = False
        super().__init__(page, fps)

    def _resolve(self) -> str:
        return resolve_stream(self.page)

    def _label(self) -> str:
        return sanitize(self.page)

    def _stream_url(self) -> str | None:
        # Не чаще раза в RESOLVE_EVERY секунд, в том числе после неудачи
        if self.resolved_at == 0.0 or time.monotonic() - self.resolved_at >= self.RESOLVE_EVERY:
            self.resolved_at = time.monotonic()
            try:
                self.direct = self._resolve()
                self.warned = False
            except Exception as e:
                if not self.warned:
                    self.warned = True
                    log.warning("источник %s: ссылка на поток не получена: %s", self._label(), sanitize(e))
                self.direct = None
        return self.direct


class IvideonSource(ResolvedSource):
    """Публичная камера Ivideon: поток FLV по ссылке из openapi, декодирует ffmpeg в 1280x720.

    Ссылка содержит токен. cv2.VideoCapture при ошибке открытия печатает адрес целиком в stderr,
    поэтому поток читает подпроцесс ffmpeg с -loglevel quiet и без stderr: токен не попадает в лог.
    """

    WIDTH, HEIGHT = 1280, 720

    def __init__(self, page: str, fps: float):
        self.camera_id = ivideon.camera_id(page)
        self.show_fps = fps
        super().__init__(page, fps)

    def _run(self) -> None:
        size = self.WIDTH * self.HEIGHT * 3
        while not self.stopped.is_set():
            url = self._stream_url()
            if url:
                proc = subprocess.Popen(
                    ["ffmpeg", "-loglevel", "quiet", "-nostdin", "-i", url, "-an",
                     "-vf", f"scale={self.WIDTH}:{self.HEIGHT},fps={self.show_fps:g}",
                     "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                self.proc = proc
                try:
                    while not self.stopped.is_set():
                        data = proc.stdout.read(size)
                        if len(data) < size:
                            break
                        frame = np.frombuffer(data, np.uint8).reshape(self.HEIGHT, self.WIDTH, 3)
                        with self.lock:
                            self.last = (time.time(), frame)
                finally:
                    proc.kill()
                    proc.wait()
            self.stopped.wait(self.reconnect)

    def close(self) -> None:
        self.stopped.set()
        proc = getattr(self, "proc", None)
        if proc is not None:
            proc.kill()
        self.thread.join(timeout=3)

    def _resolve(self) -> str:
        url = ivideon.resolve(self.camera_id, "flv")
        log.info("ivideon %s: поток %s", self.camera_id, urllib.parse.urlsplit(url).hostname)
        return url

    def _label(self) -> str:
        return f"ivideon {self.camera_id}"


class _SilentLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def resolve_stream(page: str) -> str:
    """Прямая ссылка на поток страницы YouTube через yt-dlp."""
    import yt_dlp

    # Свой вывод yt-dlp в stderr отключён: причина ошибки пишется в лог один раз
    options = {"quiet": True, "no_warnings": True, "format": "best[height<=720]/best", "logger": _SilentLogger()}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(page, download=False)
    url = info.get("url") or (info.get("formats") or [{}])[-1].get("url")
    if not url:
        raise ValueError("в ответе yt-dlp нет url")
    return url


YOUTUBE_HOSTS = ("youtube.com", "youtu.be")


def _host_in(host: str | None, allowed) -> bool:
    """Хост точно совпадает с одним из allowed или является его поддоменом."""
    host = (host or "").lower().rstrip(".")
    return any(host == a or host.endswith("." + a) for a in allowed)


def _needs_resolve(source: str) -> bool:
    return _host_in(urllib.parse.urlsplit(source).hostname, YOUTUBE_HOSTS)


class FolderSource(FrameSource):
    """Папка с кадрами: файлы по имени с частотой fps."""

    def __init__(self, path: Path, fps: float):
        self.files = sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        self.pacer = _Pacer(fps)
        self.index = 0

    def read(self) -> tuple[float, np.ndarray] | None:
        self.pacer.wait()
        while True:
            if self.index >= len(self.files):
                if not _loop() or not self.files:
                    return None
                self.index = 0
            path = self.files[self.index]
            self.index += 1
            frame = cv2.imread(str(path))
            if frame is not None:
                return time.time(), frame


def open_source(source: str, fps: float) -> FrameSource:
    if source.startswith("rtsp://"):
        return RtspSource(source, fps)
    if source.startswith(("http://", "https://")):
        if ivideon.camera_id(source):
            return IvideonSource(source, fps)
        return ResolvedSource(source, fps) if _needs_resolve(source) else HttpSource(source, fps)
    path = Path(source)
    if not path.is_absolute():
        path = ROOT / path
    if path.is_file():
        return FileSource(path, fps)
    if path.is_dir():
        return FolderSource(path, fps)
    raise FileNotFoundError(f"источник не найден: {path}")
