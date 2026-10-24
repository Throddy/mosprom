"""Проверка демо-стенда: только просмотр, размытие лиц, лимит потоков, конфиг камер, трансляции.

python scripts/check_demo.py
"""
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="check_demo_"))
os.environ["CAMERAS_PATH"] = str(TMP / "cameras.local.yaml")
os.environ["DB_PATH"] = str(TMP / "events.sqlite3")

import numpy as np  # noqa: E402

from backend.cameras import load_cameras  # noqa: E402
from backend.hub import to_json  # noqa: E402
from backend.privacy import blur_people  # noqa: E402
from backend.validation import validate_camera  # noqa: E402
from core.schemas import Detection  # noqa: E402
from logic import describe  # noqa: E402

DEMO = ROOT / "configs" / "cameras.demo.yaml"
failed = False


def check(name: str, fn) -> None:
    global failed
    try:
        fn()
        print(f"ok {name}")
    except Exception as e:
        failed = True
        print(f"fail {name}: {e}")


def expect(cond: bool, reason: str) -> None:
    if not cond:
        raise AssertionError(reason)


def read_only():
    os.environ.update(READ_ONLY="1", PIPELINE="0")
    from fastapi.testclient import TestClient

    from backend.app import create_app
    try:
        c = TestClient(create_app())
        cam = c.get("/api/cameras").json()[0]
        r = c.put(f"/api/cameras/{cam['id']}", json=cam)
        expect(r.status_code == 403 and isinstance(r.json().get("detail"), str), f"PUT {r.status_code}")
        event = c.get("/api/events", params={"limit": 1}).json()["items"][0]
        r = c.patch(f"/api/events/{event['id']}", json={"status": "confirmed", "comment": None})
        expect(r.status_code == 403 and isinstance(r.json().get("detail"), str), f"PATCH {r.status_code}")
        for path in ("/api/status", "/api/cameras", "/api/events", "/api/rules", "/api/stats"):
            expect(c.get(path).status_code == 200, f"GET {path}")
    finally:
        os.environ["READ_ONLY"] = "0"


def checkerboard() -> np.ndarray:
    yy, xx = np.mgrid[0:480, 0:640]
    board = (((xx // 4) + (yy // 4)) % 2 * 255).astype(np.uint8)
    noise = (xx * 7 + yy * 13) % 251
    return np.dstack([board, noise.astype(np.uint8), 255 - board])


def colors(region: np.ndarray) -> int:
    return len(np.unique(region.reshape(-1, 3), axis=0))


def blur():
    frame = checkerboard()
    kpts = np.zeros((17, 3), np.float32)
    # Точки головы: центр (250, 150), размах 32 px, квадрат головы 80 px целиком внутри бокса
    for i, (x, y) in enumerate([(250, 154), (242, 146), (258, 146), (234, 150), (266, 150)]):
        kpts[i] = (x, y, 0.9)
    det = Detection(cls="person", conf=0.9, bbox=(200.0, 100.0, 300.0, 400.0), kpts=kpts)
    out = blur_people(frame, [det])
    head = out[130:170, 230:270]
    expect(colors(head) <= 64, f"head colors {colors(head)}")
    mask = np.ones(frame.shape[:2], bool)
    mask[100:400, 200:300] = False
    expect(np.array_equal(out[mask], frame[mask]), "outside bbox changed")


def blur_no_kpts():
    frame = checkerboard()
    det = Detection(cls="person", conf=0.9, bbox=(200.0, 100.0, 300.0, 400.0))
    out = blur_people(frame, [det])
    top = out[100:166, 200:300]
    expect(colors(top) <= 64, f"top 22% colors {colors(top)}")
    expect(np.array_equal(out[170:400, 200:300], frame[170:400, 200:300]), "below head changed")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def max_streams():
    import uvicorn

    from backend.app import create_app
    os.environ.update(MAX_STREAMS="1", PIPELINE="1", DETECTOR_BACKEND="onnx")
    os.environ.pop("CAMERAS_PATH", None)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/api/cameras/cam1/stream"
    try:
        deadline = time.time() + 30
        while not server.started and time.time() < deadline:
            time.sleep(0.2)
        first = urllib.request.urlopen(url, timeout=30)
        expect(len(first.read(1000)) > 0, "first stream empty")
        try:
            urllib.request.urlopen(url, timeout=10)
            raise AssertionError("second stream opened")
        except urllib.error.HTTPError as e:
            expect(e.code == 503, f"second stream {e.code}")
        first.close()
        reopened = False
        for _ in range(20):
            time.sleep(0.5)
            try:
                third = urllib.request.urlopen(url, timeout=10)
                third.read(100)
                third.close()
                reopened = True
                break
            except urllib.error.HTTPError as e:
                if e.code != 503:
                    raise
        expect(reopened, "stream not reopened after the first was closed")
    finally:
        server.should_exit = True
        thread.join(15)


def demo_config():
    cameras = load_cameras(DEMO)
    expect(cameras, "no cameras")
    specs = {r["type"]: r for r in describe()}
    bad = {c.id: validate_camera(to_json(c), specs) for c in cameras}
    bad = {k: v for k, v in bad.items() if v}
    expect(not bad, f"{bad}")


def stream_resolve():
    import cv2

    from backend.sources import _needs_resolve, resolve_stream
    for cam in load_cameras(DEMO):
        if not cam.id.startswith("live_"):
            continue
        t = time.time()
        try:
            if _needs_resolve(cam.source):
                direct = resolve_stream(cam.source)
                print(f"  {cam.id}: ссылка получена за {time.time() - t:.1f} с")
            else:
                cap = cv2.VideoCapture(cam.source)
                ok, frame = cap.read()
                cap.release()
                print(f"  {cam.id}: кадр {'получен ' + str(frame.shape[1]) + 'x' + str(frame.shape[0]) if ok else 'не получен'}"
                      f" за {time.time() - t:.1f} с")
        except Exception as e:
            print(f"  {cam.id}: не открылся: {str(e).splitlines()[0][:160]}")


if __name__ == "__main__":
    check("read_only", read_only)
    check("blur", blur)
    check("blur_no_kpts", blur_no_kpts)
    check("max_streams", max_streams)
    check("demo_config", demo_config)
    check("stream_resolve", stream_resolve)
    sys.exit(1 if failed else 0)
