"""Нагрузка видеопотоком: N зрителей одной камеры по HLS или MJPEG, байты, Мбит/с, ошибки, CPU бэкенда.

python scripts/load_test.py --base http://127.0.0.1:8000 --camera demo_reel --viewers 50 --seconds 60
    [--mode hls|mjpeg] [--pid PID]

hls: зритель раз в 1 с читает /hls/<camera>/index.m3u8 и скачивает новые сегменты.
mjpeg: зритель читает /api/cameras/<camera>/stream и считает байты.
"""
import argparse
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class Viewer(threading.Thread):
    def __init__(self, mode: str, base: str, camera: str, until: float):
        super().__init__(daemon=True)
        self.mode, self.base, self.camera, self.until = mode, base.rstrip("/"), camera, until
        self.bytes = 0
        self.segments = 0
        self.errors: list[str] = []

    def run(self) -> None:
        try:
            self._hls() if self.mode == "hls" else self._mjpeg()
        except Exception as e:
            self.errors.append(f"{type(e).__name__}: {e}")

    def _get(self, url: str) -> bytes:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = r.read()
        self.bytes += len(data)
        return data

    def _hls(self) -> None:
        playlist = f"{self.base}/hls/{urllib.parse.quote(self.camera)}/index.m3u8"
        seen: set[str] = set()
        while time.time() < self.until:
            started = time.time()
            try:
                text = self._get(playlist).decode("utf-8", "replace")
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and line not in seen:
                        seen.add(line)
                        self._get(urllib.parse.urljoin(playlist, line))
                        self.segments += 1
            except (urllib.error.URLError, OSError) as e:
                self.errors.append(f"{type(e).__name__}: {e}")
            time.sleep(max(0.0, 1.0 - (time.time() - started)))

    def _mjpeg(self) -> None:
        url = f"{self.base}/api/cameras/{urllib.parse.quote(self.camera)}/stream"
        with urllib.request.urlopen(url, timeout=10) as r:
            while time.time() < self.until:
                chunk = r.read1(65536)
                if not chunk:
                    break
                self.bytes += len(chunk)


def cpu_percent(pid: int) -> float | None:
    out = subprocess.run(["ps", "-p", str(pid), "-o", "%cpu="], capture_output=True, text=True).stdout.strip()
    return float(out) if out else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Нагрузка видеопотоком")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--camera", default="demo_reel")
    parser.add_argument("--viewers", type=int, default=50)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--mode", choices=("hls", "mjpeg"), default="hls")
    parser.add_argument("--pid", type=int, help="PID процесса бэкенда для замера CPU")
    args = parser.parse_args()

    started = time.time()
    until = started + args.seconds
    viewers = [Viewer(args.mode, args.base, args.camera, until) for _ in range(args.viewers)]
    for v in viewers:
        v.start()
    cpu = []
    while time.time() < until:
        time.sleep(5)
        if args.pid:
            value = cpu_percent(args.pid)
            if value is not None:
                cpu.append(value)
    for v in viewers:
        v.join(15)
    elapsed = time.time() - started
    total = sum(v.bytes for v in viewers)
    errors = [e for v in viewers for e in v.errors]
    mbps = total * 8 / elapsed / 1e6
    print(f"режим {args.mode}, камера {args.camera}, зрителей {args.viewers}, {elapsed:.0f} с")
    print(f"всего {total / 1e6:.1f} МБ, {mbps:.1f} Мбит/с суммарно, {mbps / max(args.viewers, 1):.2f} Мбит/с на зрителя")
    if args.mode == "hls":
        print(f"сегментов на зрителя в среднем {sum(v.segments for v in viewers) / max(args.viewers, 1):.1f}")
    print(f"ошибок {len(errors)}" + (f", первая: {errors[0][:160]}" if errors else ""))
    if cpu:
        print(f"CPU бэкенда: среднее {sum(cpu) / len(cpu):.0f} %, макс {max(cpu):.0f} %")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
