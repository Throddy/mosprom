"""Нагрузка видеопотоком: N зрителей одной камеры по HLS или MJPEG, байты, Мбит/с, ошибки, CPU бэкенда.

python scripts/load_test.py --base http://127.0.0.1:8000 --camera demo_reel --viewers 50 --seconds 60
    [--mode hls|mjpeg|mix] [--monitor M] [--pid PID]

hls: зритель раз в 1 с читает /hls/<camera>/index.m3u8 и скачивает новые сегменты.
mjpeg: зритель читает /api/cameras/<camera>/stream и считает байты.
mix: --viewers зрителей HLS и --monitor зрителей «Монитора»: раз в 2 с /frame?w=480 всех камер из
/api/cameras, раз в 5 с /api/events?limit=50.
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
        self.api_ms: list[float] = []

    def run(self) -> None:
        try:
            {"hls": self._hls, "mjpeg": self._mjpeg, "monitor": self._monitor}[self.mode]()
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

    def _timed(self, url: str) -> bytes:
        started = time.time()
        data = self._get(url)
        self.api_ms.append((time.time() - started) * 1000.0)
        return data

    def _monitor(self) -> None:
        import json
        cameras = [c["id"] for c in json.loads(self._timed(f"{self.base}/api/cameras"))]
        next_events = 0.0
        while time.time() < self.until:
            started = time.time()
            try:
                for camera_id in cameras:
                    self._timed(f"{self.base}/api/cameras/{urllib.parse.quote(camera_id)}/frame?w=480&t={started:.0f}")
                if started >= next_events:
                    self._timed(f"{self.base}/api/events?limit=50")
                    next_events = started + 5.0
            except (urllib.error.URLError, OSError) as e:
                self.errors.append(f"{type(e).__name__}: {e}")
            time.sleep(max(0.0, 2.0 - (time.time() - started)))

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
    parser.add_argument("--mode", choices=("hls", "mjpeg", "mix"), default="hls")
    parser.add_argument("--monitor", type=int, default=0, help="mix: зрителей «Монитора»")
    parser.add_argument("--pid", type=int, help="PID процесса бэкенда для замера CPU")
    args = parser.parse_args()

    started = time.time()
    until = started + args.seconds
    mode = "hls" if args.mode == "mix" else args.mode
    viewers = [Viewer(mode, args.base, args.camera, until) for _ in range(args.viewers)]
    monitors = [Viewer("monitor", args.base, args.camera, until) for _ in range(args.monitor if args.mode == "mix" else 0)]
    for v in viewers + monitors:
        v.start()
    cpu = []
    while time.time() < until:
        time.sleep(5)
        if args.pid:
            value = cpu_percent(args.pid)
            if value is not None:
                cpu.append(value)
    for v in viewers + monitors:
        v.join(15)
    elapsed = time.time() - started
    total = sum(v.bytes for v in viewers + monitors)
    errors = [e for v in viewers + monitors for e in v.errors]
    mbps = total * 8 / elapsed / 1e6
    print(f"режим {args.mode}, камера {args.camera}, зрителей {args.viewers}"
          + (f" + «Монитор» {len(monitors)}" if monitors else "") + f", {elapsed:.0f} с")
    if monitors:
        hls_mbps = sum(v.bytes for v in viewers) * 8 / elapsed / 1e6
        mon_mbps = sum(v.bytes for v in monitors) * 8 / elapsed / 1e6
        api = sorted(x for v in monitors for x in v.api_ms)
        p95 = api[int(0.95 * (len(api) - 1))] if api else None
        print(f"всего {total / 1e6:.1f} МБ, {mbps:.1f} Мбит/с суммарно")
        print(f"HLS: {hls_mbps / max(len(viewers), 1):.2f} Мбит/с на зрителя, «Монитор»: "
              f"{mon_mbps / len(monitors):.2f} Мбит/с на зрителя")
        print(f"API «Монитора»: запросов {len(api)}, p95 {p95:.0f} мс" if p95 is not None else "API: запросов нет")
    else:
        print(f"всего {total / 1e6:.1f} МБ, {mbps:.1f} Мбит/с суммарно, {mbps / max(args.viewers, 1):.2f} Мбит/с на зрителя")
    if args.mode == "hls":
        print(f"сегментов на зрителя в среднем {sum(v.segments for v in viewers) / max(args.viewers, 1):.1f}")
    print(f"ошибок {len(errors)}" + (f", первая: {errors[0][:160]}" if errors else ""))
    if cpu:
        print(f"CPU бэкенда: среднее {sum(cpu) / len(cpu):.0f} %, макс {max(cpu):.0f} %")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
