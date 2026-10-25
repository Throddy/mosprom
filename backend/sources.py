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
from backend.validation import remote_allowed, sanitize

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


class _FfmpegReader:
    """Чтение потока подпроцессом ffmpeg без вывода: кадры bgr24 заданного размера через pipe.

    Наследник задаёт _stream_url(), _input_args() и _frame_size(url). ffmpeg запускается с -loglevel quiet
    и без stderr: адрес потока, в том числе с токеном, в лог не попадает.
    """

    def _input_args(self) -> list[str]:
        return []

    def _frame_size(self, url: str) -> tuple[int, int]:
        raise NotImplementedError

    def _run(self) -> None:
        while not self.stopped.is_set():
            url = self._stream_url()
            if url:
                self._read_ffmpeg(url)
            self.stopped.wait(self.reconnect)

    def _read_ffmpeg(self, url: str) -> None:
        width, height = self._frame_size(url)
        size = width * height * 3
        proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "quiet", "-nostdin", *self._input_args(), "-i", url, "-an",
             "-vf", f"scale={width}:{height},fps={self.show_fps:g}",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.proc = proc
        try:
            while not self.stopped.is_set():
                data = proc.stdout.read(size)
                if len(data) < size:
                    break
                frame = np.frombuffer(data, np.uint8).reshape(height, width, 3)
                with self.lock:
                    self.last = (time.time(), frame)
        finally:
            proc.kill()
            proc.wait()

    def close(self) -> None:
        self.stopped.set()
        proc = getattr(self, "proc", None)
        if proc is not None:
            proc.kill()
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
    return hls_variant_size(url, max_height)[0]


MAX_VARIANT_WIDTH = 1920  # вариант шире выбирается, только если уже нет; кадры тогда уменьшаются до 1280
SCALE_WIDTH = 1280


def hls_variant_size(url: str, max_height: int = 720) -> tuple[str, int, int]:
    """Как hls_variant, плюс ширина и высота варианта из RESOLUTION; 0, 0 — если не указаны.
    Варианты шире MAX_VARIANT_WIDTH берутся, только если других нет."""
    request = urllib.request.Request(url, headers={"User-Agent": ivideon.HEADERS["User-Agent"]})
    with urllib.request.urlopen(request, timeout=15, context=ivideon._context()) as r:
        text = r.read(65536).decode("utf-8", "replace")
    variants, height = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF"):
            m = re.search(r"RESOLUTION=(\d+)x(\d+)", line)
            width, height = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        elif line and not line.startswith("#") and height is not None:
            variants.append((height, width, urllib.parse.urljoin(url, line)))
            height = None
    if not variants:
        return url, 0, 0
    narrow = [v for v in variants if v[1] <= MAX_VARIANT_WIDTH] or variants
    fit = [v for v in narrow if 0 < v[0] <= max_height]
    height, width, variant = max(fit) if fit else min(narrow)
    return variant, width, height


class HlsSource(_FfmpegReader, HttpSource):
    """HLS .m3u8: вариант до 720p, чтение ffmpeg с -re — кадры идут в темпе видео, а не пачками по сегментам.
    Размер кадра — из RESOLUTION варианта, без него — ffprobe; высота не больше 720."""

    MAX_HEIGHT = 720

    def __init__(self, url: str, fps: float):
        self.show_fps = fps
        self.size: tuple[int, int] | None = None
        super().__init__(url, fps)

    def _stream_url(self) -> str | None:
        try:
            variant, width, height = hls_variant_size(self.url, self.MAX_HEIGHT)
        except Exception as e:
            log.warning("источник %s: плейлист HLS не прочитан: %s", sanitize(ivideon.safe(self.url)), sanitize(e))
            variant, width, height = self.url, 0, 0
        self.size = (width, height) if width and height else None
        # Адрес варианта из плейлиста проверяется по REMOTE_HOSTS так же, как адрес источника. Вариант
        # удалённого плейлиста — только http(s); локальный плейлист file:// (проверки) — только file://
        master = urllib.parse.urlsplit(self.url).scheme
        scheme = urllib.parse.urlsplit(variant).scheme
        if master in ("http", "https"):
            allowed = scheme in ("http", "https") and remote_allowed(variant)
        else:
            allowed = scheme == master
        if variant != self.url and not allowed:
            log.warning("источник %s: хост варианта HLS %s не входит в REMOTE_HOSTS, камера не открыта",
                        sanitize(ivideon.safe(self.url)), sanitize(urllib.parse.urlsplit(variant).hostname))
            return None
        return variant

    def _input_args(self) -> list[str]:
        return ["-re"]

    def _frame_size(self, url: str) -> tuple[int, int]:
        width, height = self.size or _probe_size(url)
        if width <= 0 or height <= 0:
            width, height = 1280, 720
        if width > MAX_VARIANT_WIDTH:
            # Ширина из плейлиста не ограничена: кадры уменьшаются в ffmpeg сразу после декодирования
            width, height = SCALE_WIDTH, round(height * SCALE_WIDTH / width)
        if height > self.MAX_HEIGHT:
            width, height = round(width * self.MAX_HEIGHT / height), self.MAX_HEIGHT
        return max(width - width % 2, 2), max(height - height % 2, 2)


def _probe_size(url: str) -> tuple[int, int]:
    """Размер видео через ffprobe без вывода ошибок; при неудаче — 1280x720."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", url], capture_output=True, text=True, timeout=20).stdout.strip()
        width, height = (int(x) for x in out.split(",")[:2])
        return width, height
    except Exception:
        return 1280, 720


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


class IvideonSource(_FfmpegReader, ResolvedSource):
    """Публичная камера Ivideon: поток FLV по ссылке из openapi, декодирует ffmpeg в 1280x720.

    Ссылка содержит токен. cv2.VideoCapture при ошибке открытия печатает адрес целиком в stderr,
    поэтому поток читает подпроцесс ffmpeg с -loglevel quiet и без stderr: токен не попадает в лог.
    """

    WIDTH, HEIGHT = 1280, 720

    def __init__(self, page: str, fps: float):
        self.camera_id = ivideon.camera_id(page)
        self.show_fps = fps
        super().__init__(page, fps)

    def _frame_size(self, url: str) -> tuple[int, int]:
        return self.WIDTH, self.HEIGHT

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
        if _needs_resolve(source):
            return ResolvedSource(source, fps)
        if urllib.parse.urlsplit(source).path.endswith(".m3u8"):
            return HlsSource(source, fps)
        return HttpSource(source, fps)
    path = Path(source)
    if not path.is_absolute():
        path = ROOT / path
    if path.is_file():
        return FileSource(path, fps)
    if path.is_dir():
        return FolderSource(path, fps)
    raise FileNotFoundError(f"источник не найден: {path}")
