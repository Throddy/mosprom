"""Источники кадров: видеофайл, RTSP, HTTP(S) поток, страница YouTube или Ivideon, папка с кадрами."""
import logging
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

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

    def _grab_frame(self) -> np.ndarray | None:
        target = int(self.pos)
        while self.index < target:
            if not self.cap.grab():
                return None
            self.index += 1
        ok, frame = self.cap.read()
        if not ok:
            return None
        self.index += 1
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
    """HTTP(S) поток, например HLS .m3u8: как RTSP, переподключение каждые 5 с."""

    reconnect = 5.0


class ResolvedSource(HttpSource):
    """Страница YouTube или Ivideon: прямая ссылка на поток берётся через yt-dlp.
    При обрыве ссылка получается заново, но не чаще раза в RESOLVE_EVERY секунд."""

    RESOLVE_EVERY = 60.0

    def __init__(self, page: str, fps: float):
        self.page = page
        self.direct: str | None = None
        self.resolved_at = 0.0
        self.warned = False
        super().__init__(page, fps)

    def _stream_url(self) -> str | None:
        # Не чаще раза в RESOLVE_EVERY секунд, в том числе после неудачи
        if self.resolved_at == 0.0 or time.monotonic() - self.resolved_at >= self.RESOLVE_EVERY:
            self.resolved_at = time.monotonic()
            try:
                self.direct = resolve_stream(self.page)
                self.warned = False
            except Exception as e:
                if not self.warned:
                    self.warned = True
                    log.warning("источник %s: ссылка на поток не получена: %s", sanitize(self.page), sanitize(e))
                self.direct = None
        return self.direct


class _SilentLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def resolve_stream(page: str) -> str:
    """Прямая ссылка на поток страницы YouTube или Ivideon через yt-dlp."""
    import yt_dlp

    # Свой вывод yt-dlp в stderr отключён: причина ошибки пишется в лог один раз
    options = {"quiet": True, "no_warnings": True, "format": "best[height<=720]/best", "logger": _SilentLogger()}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(page, download=False)
    url = info.get("url") or (info.get("formats") or [{}])[-1].get("url")
    if not url:
        raise ValueError("в ответе yt-dlp нет url")
    return url


def _needs_resolve(source: str) -> bool:
    return any(host in source for host in ("youtube.com/", "youtu.be/", "ivideon.com/"))


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
        return ResolvedSource(source, fps) if _needs_resolve(source) else HttpSource(source, fps)
    path = Path(source)
    if not path.is_absolute():
        path = ROOT / path
    if path.is_file():
        return FileSource(path, fps)
    if path.is_dir():
        return FolderSource(path, fps)
    raise FileNotFoundError(f"источник не найден: {path}")
