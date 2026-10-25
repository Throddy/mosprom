"""HLS кадров показа: на камеру один процесс ffmpeg (libx264) пишет сегменты в HLS_DIR/<camera_id>/.

Кадры те же, что в общем MJPEG: с задержкой синхронизации, разметкой и размытием (BE-18). Сегменты раздаются
статикой (/hls в backend/app.py, на стенде — Caddy), нагрузка на кодирование не зависит от числа зрителей.

HLS_ENABLED (0), HLS_DIR (backend/data/hls), HLS_BITRATE (1800k).
"""
import logging
import os
import re
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
RESTART_EVERY = 5.0


def hls_enabled() -> bool:
    return os.environ.get("HLS_ENABLED", "0") == "1"


def hls_dir() -> Path:
    path = Path(os.environ.get("HLS_DIR") or "backend/data/hls")
    return path if path.is_absolute() else ROOT / path


def hls_bitrate() -> str:
    return os.environ.get("HLS_BITRATE", "1800k")


def _scaled(bitrate: str, k: float) -> str:
    """1800k * 1.3 -> 2340k; число без суффикса — в битах/с."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kKmM]?)", bitrate.strip())
    if not m:
        raise ValueError(f"HLS_BITRATE: {bitrate}")
    return f"{int(float(m.group(1)) * k)}{m.group(2).lower()}"


class HlsWriter:
    """Кадры BGR в ffmpeg; при падении ffmpeg перезапуск не чаще раза в RESTART_EVERY с."""

    def __init__(self, camera_id: str, width: int, height: int, fps: float, out_dir: Path):
        self.camera_id = camera_id
        self.width, self.height = width - width % 2, height - height % 2
        self.fps = max(fps, 1.0)
        self.out_dir = Path(out_dir)
        self.proc: subprocess.Popen | None = None
        self.started_at = 0.0
        self.warned = False
        # Сегменты прошлого запуска удаляются: плейлист начинается заново
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for old in list(self.out_dir.glob("seg_*.ts")) + list(self.out_dir.glob("index.m3u8")):
            old.unlink(missing_ok=True)
        self._start()

    def _command(self) -> list[str]:
        gop = str(int(round(2 * self.fps)))
        rate = hls_bitrate()
        return [
            "ffmpeg", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{self.width}x{self.height}", "-r", f"{self.fps:g}", "-i", "pipe:0",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-pix_fmt", "yuv420p",
            "-g", gop, "-keyint_min", gop, "-sc_threshold", "0",
            "-b:v", rate, "-maxrate", _scaled(rate, 1.3), "-bufsize", _scaled(rate, 2.0),
            "-f", "hls", "-hls_time", "2", "-hls_list_size", "6",
            "-hls_flags", "delete_segments+independent_segments+omit_endlist",
            "-hls_segment_filename", str(self.out_dir / "seg_%05d.ts"), str(self.out_dir / "index.m3u8"),
        ]

    def _start(self) -> None:
        self.started_at = time.monotonic()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.proc = subprocess.Popen(self._command(), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
        except OSError as e:
            self.proc = None
            log.warning("hls %s: ffmpeg не запущен: %s", self.camera_id, e)

    def write(self, frame: np.ndarray) -> None:
        if self.proc is None or self.proc.poll() is not None:
            if time.monotonic() - self.started_at < RESTART_EVERY:
                return
            if not self.warned:
                self.warned = True
                log.warning("hls %s: ffmpeg завершился, перезапуск не чаще раза в %g с", self.camera_id, RESTART_EVERY)
            self._start()
            if self.proc is None:
                return
        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
        try:
            self.proc.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
        except (BrokenPipeError, ValueError, OSError):
            # Процесс упал: следующий write перезапустит его не раньше RESTART_EVERY
            self.proc.kill()

    def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
            proc.wait()
