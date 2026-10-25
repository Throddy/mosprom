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


def env_demo() -> dict:
    out = {}
    for line in (ROOT / "deploy" / "env.demo").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def demo_config():
    # Камеры стенда проверяются с REMOTE_HOSTS из deploy/env.demo
    os.environ["REMOTE_HOSTS"] = env_demo().get("REMOTE_HOSTS", "")
    cameras = load_cameras(DEMO)
    expect(cameras, "no cameras")
    specs = {r["type"]: r for r in describe()}
    bad = {c.id: validate_camera(to_json(c), specs) for c in cameras}
    bad = {k: v for k, v in bad.items() if v}
    expect(not bad, f"{bad}")


def stream_resolve():
    import cv2

    from backend import ivideon
    from backend.sources import IvideonSource, _needs_resolve, hls_variant, resolve_stream
    for cam in load_cameras(DEMO):
        if not cam.id.startswith("live_"):
            continue
        t = time.time()
        try:
            if ivideon.camera_id(cam.source):
                # Ссылку с токеном открывает только IvideonSource: OpenCV печатает адрес при ошибке
                src = IvideonSource(cam.source, cam.fps)
                end = time.time() + 30
                item = None
                while item is None and time.time() < end and src.thread.is_alive():
                    with src.lock:
                        item = src.last
                    time.sleep(0.2)
                src.close()
                got = f"кадр {item[1].shape[1]}x{item[1].shape[0]}" if item else "кадр не получен"
                print(f"  {cam.id}: ivideon flv через ffmpeg, {got} за {time.time() - t:.1f} с")
                continue
            elif _needs_resolve(cam.source):
                url = resolve_stream(cam.source)
                how = "yt-dlp"
            else:
                url = hls_variant(cam.source) if cam.source.endswith(".m3u8") else cam.source
                how = ivideon.safe(url)
            cap = cv2.VideoCapture(url)
            ok, frame = cap.read()
            cap.release()
            got = f"кадр {frame.shape[1]}x{frame.shape[0]}" if ok else "кадр не получен"
            print(f"  {cam.id}: {how}, {got} за {time.time() - t:.1f} с")
        except Exception as e:
            print(f"  {cam.id}: не открылся: {str(e).splitlines()[0][:160]}")


def remote_hosts():
    from backend.validation import remote_allowed
    os.environ["REMOTE_HOSTS"] = "stream.terem-pro.ru"
    expect(remote_allowed("https://stream.terem-pro.ru/x.m3u8"), "allowed host rejected")
    for bad in ("https://evil.example/?stream.terem-pro.ru", "http://127.0.0.1/",
                "https://stream.terem-pro.ru.evil.example/"):
        expect(not remote_allowed(bad), f"{bad} allowed")


def mjpeg_frames(url: str, seconds: float, out: list) -> None:
    """Собрать JPEG-кадры из MJPEG-потока за seconds секунд."""
    r = urllib.request.urlopen(url, timeout=30)
    buf, end = b"", time.time() + seconds
    try:
        while time.time() < end:
            buf += r.read1(65536)
            while True:
                s0 = buf.find(b"\xff\xd8")
                e0 = buf.find(b"\xff\xd9", s0 + 2) if s0 >= 0 else -1
                if s0 < 0 or e0 < 0:
                    break
                out.append(buf[s0:e0 + 2])
                buf = buf[e0 + 2:]
    finally:
        r.close()


def stream_server(camera_fps: float):
    """uvicorn с одной камерой data/demo.mp4 на camera_fps, STREAM_FPS=15. Возвращает (app, server, thread, port)."""
    import uvicorn
    import yaml

    from backend.app import create_app
    cams = TMP / f"cameras_{camera_fps:g}.yaml"
    cams.write_text(yaml.safe_dump({"cameras": [{"id": "s1", "name": "s1", "source": "data/demo.mp4",
                                                 "fps": camera_fps, "zones": [], "rules": []}]}), encoding="utf-8")
    os.environ.update(PIPELINE="1", DETECTOR_BACKEND="onnx", STREAM_FPS="15", MAX_STREAMS="30",
                      CAMERAS_PATH=str(cams), BLUR_FACES="1")
    app = create_app()
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.2)
    return app, server, thread, port


def shared_mjpeg():
    app, server, thread, port = stream_server(5)
    url = f"http://127.0.0.1:{port}/api/cameras/s1/stream"
    try:
        time.sleep(3)
        enc = app.state.mjpeg["encodes"]
        one: list = []
        before = enc.get("s1", 0)
        mjpeg_frames(url, 2.0, one)
        n1 = enc.get("s1", 0) - before
        outs = [[], [], []]
        before = enc.get("s1", 0)
        threads = [threading.Thread(target=mjpeg_frames, args=(url, 2.0, o)) for o in outs]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        n3 = enc.get("s1", 0) - before
        common = set(outs[0]) & set(outs[1]) & set(outs[2])
        expect(len(common) > 0, "three clients got no identical frame bytes")
        expect(n3 <= n1 * 1.3 + 3, f"encodes: 1 client {n1}, 3 clients {n3}")
        print(f"  кадров у клиентов {[len(o) for o in outs]}, общих {len(common)}; сжатий за 2 с: 1 клиент {n1}, 3 клиента {n3}")
    finally:
        server.should_exit = True
        thread.join(15)


def stream_fps():
    app, server, thread, port = stream_server(5)
    url = f"http://127.0.0.1:{port}/api/cameras/s1/stream"
    try:
        time.sleep(3)
        frames: list = []
        t0 = time.time()
        mjpeg_frames(url, 4.0, frames)
        cam = app.state.pipeline_state["pipeline"].cams["s1"]
        processed = sum(1 for t in list(cam.processed) if t >= t0)
        print(f"  /stream за 4 с: {len(frames)} кадров, детектор: {processed}")
        expect(len(frames) >= 40, f"/stream {len(frames)} frames in 4 s")
        expect(processed <= 25, f"detector {processed} frames in 4 s")
    finally:
        server.should_exit = True
        thread.join(15)


BLUE = (255, 0, 0)


class BlueDetector:
    """Заглушка детектора: человек — синие пиксели кадра, ответ с задержкой delay с."""
    name = "stub"

    def __init__(self, delay: float, head_share: float = 0.0):
        self.delay = delay
        self.head_share = head_share  # доля бокса над синим прямоугольником: голова

    def infer(self, frames):
        time.sleep(self.delay)
        out = []
        for frame in frames:
            mask = (frame[:, :, 0] > 200) & (frame[:, :, 1] < 60) & (frame[:, :, 2] < 60)
            ys, xs = np.nonzero(mask)
            if len(xs) < 50:
                out.append([])
                continue
            y1, y2 = float(ys.min()), float(ys.max())
            head = (y2 - y1) * self.head_share / (1 - self.head_share) if self.head_share else 0.0
            out.append([Detection(cls="person", conf=0.9, bbox=(float(xs.min()), y1 - head, float(xs.max()), y2))])
        return out


def synthetic_server(frames: list, camera_fps: float, detector, extra_env: dict):
    """uvicorn с одной камерой live_s на папке кадров и заглушкой детектора. Возвращает (server, thread, port)."""
    import cv2
    import uvicorn
    import yaml

    import ml
    from backend.app import create_app
    folder = Path(tempfile.mkdtemp(prefix="frames_", dir=TMP))
    for i, frame in enumerate(frames):
        cv2.imwrite(str(folder / f"{i:04d}.png"), frame)
    cams = folder / "cameras.yaml"
    cams.write_text(yaml.safe_dump({"cameras": [{"id": "live_s", "name": "s", "source": str(folder),
                                                 "fps": camera_fps, "zones": [], "rules": []}]}), encoding="utf-8")
    os.environ.update(PIPELINE="1", DETECTOR_BACKEND="onnx", MAX_STREAMS="30", CAMERAS_PATH=str(cams),
                      STREAM_WIDTH="0", STREAM_DELAY="auto", TILED_CAMERAS="", SOURCE_LOOP="1", **extra_env)
    ml.create_detector = lambda *a, **k: detector
    app = create_app()
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.2)
    return server, thread, port


def decode(jpeg: bytes):
    import cv2
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


def stream_sync():
    # Человек — синий прямоугольник 400x200, сдвиг 20 px на кадр показа (STREAM_FPS=5), камера 1 кадр/с,
    # детектор отвечает через 1 с. Рамка (зелёная) в кадре /stream совпадает с человеком
    import ml
    original = ml.create_detector
    frames = []
    for i in range(70):
        f = np.full((360, 1900, 3), 40, np.uint8)
        x = 50 + 20 * i
        f[100:300, x:x + 400] = BLUE
        frames.append(f)
    server, thread, port = synthetic_server(frames, 1, BlueDetector(1.0), {"STREAM_FPS": "5", "BLUR_FACES": "0"})
    try:
        time.sleep(4.0)
        jpegs: list = []
        mjpeg_frames(f"http://127.0.0.1:{port}/api/cameras/live_s/stream", 6.0, jpegs)
        errors = []
        for jpeg in jpegs:
            img = decode(jpeg).astype(int)
            blue = (img[:, :, 0] > 180) & (img[:, :, 1] < 90) & (img[:, :, 2] < 90)
            green = (img[:, :, 1] > 180) & (img[:, :, 0] < 90) & (img[:, :, 2] < 90)
            if blue.sum() < 1000 or green.sum() < 100:
                continue
            bx = np.nonzero(blue)[1]
            gx = np.nonzero(green)[1]
            errors.append(abs((gx.min() + gx.max()) / 2 - (bx.min() + bx.max()) / 2))
        print(f"  кадров {len(jpegs)}, с рамкой {len(errors)}, расхождение центров: "
              f"макс {max(errors) if errors else None} px")
        expect(len(errors) >= 10, f"frames with box {len(errors)}")
        expect(max(errors) < 10, f"max center error {max(errors):.1f} px")
    finally:
        server.should_exit = True
        thread.join(15)
        ml.create_detector = original


def blur_new_person():
    # Фон без людей 6 с, затем человек: синее тело и голова-шахматка сверху (22 % бокса).
    # На первом кадре /stream, где человек есть, голова пикселизирована
    import ml
    original = ml.create_detector
    # Серая шахматка: без синих пикселей, чтобы заглушка не приняла голову за тело
    gray = checkerboard()[:60, :80, 0]
    board = np.dstack([gray, gray, gray])
    frames = []
    for i in range(80):
        # Голова 60 px — верхние 22 % бокса высотой 273 px, как в privacy.head_box без точек
        f = np.full((480, 640, 3), 40, np.uint8)
        if i >= 30:
            f[140:200, 280:360] = board
            f[200:413, 280:360] = BLUE
        frames.append(f)
    server, thread, port = synthetic_server(frames, 2, BlueDetector(0.3, head_share=60 / 273),
                                            {"STREAM_FPS": "5", "BLUR_FACES": "1"})
    try:
        jpegs: list = []
        mjpeg_frames(f"http://127.0.0.1:{port}/api/cameras/live_s/stream", 12.0, jpegs)
        first = None
        for jpeg in jpegs:
            img = decode(jpeg).astype(int)
            blue = (img[:, :, 0] > 180) & (img[:, :, 1] < 90) & (img[:, :, 2] < 90)
            if blue.sum() > 1000:
                first = img
                break
        expect(first is not None, "person never shown")
        # Резкость: средний перепад соседних пикселей канала 0. Шахматка меняется каждые 4 px, после
        # пикселизации — только на границах блоков. Сравнение с неразмытой головой после того же JPEG
        import cv2

        def sharpness(region):
            return float(np.abs(np.diff(region[:, :, 0].astype(int), axis=1)).mean())
        raw = sharpness(decode(cv2.imencode(".jpg", board, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()))
        head = sharpness(first[140:200, 280:360])
        print(f"  первый кадр с человеком: резкость головы {head:.1f}, без размытия {raw:.1f}")
        expect(head < 0.7 * raw, f"head sharpness {head:.1f}, raw {raw:.1f}")
    finally:
        server.should_exit = True
        thread.join(15)
        ml.create_detector = original


def plain_server(env: dict):
    """uvicorn с PIPELINE=0 и заданным окружением. Возвращает (app, server, thread, port)."""
    import uvicorn

    from backend.app import create_app
    os.environ.update(PIPELINE="0", **env)
    app = create_app()
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.2)
    return app, server, thread, port


def put_status(port: int, camera: dict, headers: dict | None = None) -> int:
    import json
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/cameras/{camera['id']}", method="PUT",
                                 data=json.dumps(camera).encode(), headers={"Content-Type": "application/json",
                                                                             **(headers or {})})
    try:
        return urllib.request.urlopen(req, timeout=10).status
    except urllib.error.HTTPError as e:
        return e.code


def admin_local():
    import json
    edits = TMP / "admin_cameras.local.yaml"
    env = {"READ_ONLY": "1", "CAMERAS_PATH": str(edits), "CAMERAS_BASE": "configs/cameras.yaml"}
    try:
        for admin, cases in (("1", [({}, 200), ({"X-Forwarded-For": "203.0.113.5"}, 403),
                                    ({"X-Real-IP": "203.0.113.5"}, 403), ({"Forwarded": "for=203.0.113.5"}, 403)]),
                             ("0", [({}, 403)])):
            _, server, thread, port = plain_server({**env, "ADMIN_LOCAL": admin})
            try:
                cam = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/cameras", timeout=10).read())[0]
                for headers, want in cases:
                    got = put_status(port, cam, headers)
                    expect(got == want, f"ADMIN_LOCAL={admin} headers {list(headers)}: {got}, want {want}")
            finally:
                server.should_exit = True
                thread.join(15)
    finally:
        os.environ.update(READ_ONLY="0", ADMIN_LOCAL="0")
        os.environ.pop("CAMERAS_BASE", None)


def cameras_base():
    import hashlib
    import shutil

    from fastapi.testclient import TestClient

    from backend.app import create_app
    base = TMP / "base_cameras.yaml"
    shutil.copy(ROOT / "configs" / "cameras.yaml", base)
    digest = hashlib.sha256(base.read_bytes()).hexdigest()
    edits = TMP / "base_cameras.local.yaml"
    edits.unlink(missing_ok=True)
    os.environ.update(PIPELINE="0", READ_ONLY="0", CAMERAS_BASE=str(base), CAMERAS_PATH=str(edits))
    try:
        c = TestClient(create_app())
        cam = c.get("/api/cameras").json()[0]
        expect([x["id"] for x in c.get("/api/cameras").json()] == [x.id for x in load_cameras(base)], "base not read")
        cam["name"] = "admin edit"
        r = c.put(f"/api/cameras/{cam['id']}", json=cam)
        expect(r.status_code == 200, f"PUT {r.status_code}")
        expect(edits.exists(), "edits file not created")
        expect(hashlib.sha256(base.read_bytes()).hexdigest() == digest, "base changed")
        again = TestClient(create_app()).get("/api/cameras").json()[0]
        expect(again["name"] == "admin edit", f"restart read {again['name']}")
    finally:
        os.environ.pop("CAMERAS_BASE", None)
        os.environ["CAMERAS_PATH"] = str(TMP / "cameras.local.yaml")


def events_keep():
    import uuid

    from fastapi.testclient import TestClient

    from backend.app import MEDIA_DIR, create_app
    from core.schemas import Event
    os.environ.update(PIPELINE="0", READ_ONLY="0", EVENTS_KEEP_MINUTES="60", FIXTURE_WS_INTERVAL="3600")
    folder = MEDIA_DIR / "check_events_keep"
    folder.mkdir(parents=True, exist_ok=True)
    now = time.time()
    try:
        app = create_app()
        db = app.state.store.db
        cases = {"old_closed": (now - 7200, now - 7100), "old_open": (now - 7200, None),
                 "new_closed": (now - 60, now - 30)}
        ids = {}
        for name, (ts, ts_end) in cases.items():
            eid = uuid.uuid4().hex
            ids[name] = eid
            (folder / f"{eid}.jpg").write_bytes(b"jpg")
            db.insert(Event(id=eid, camera_id="cam1", type="fall", severity="critical", track_id=1,
                            bbox=(0.0, 0.0, 1.0, 1.0), conf=0.9, ts_start=ts, ts_confirm=ts, ts_end=ts_end),
                      f"check_events_keep/{eid}.jpg")
        with TestClient(app):
            time.sleep(1.5)
        expect(db.get(ids["old_closed"]) is None, "old closed event kept")
        expect(not (folder / f"{ids['old_closed']}.jpg").exists(), "old snapshot kept")
        expect(db.get(ids["old_open"]) is not None, "open event deleted")
        expect(db.get(ids["new_closed"]) is not None and (folder / f"{ids['new_closed']}.jpg").exists(),
               "recent event deleted")
    finally:
        os.environ["EVENTS_KEEP_MINUTES"] = "0"
        for f in folder.glob("*"):
            f.unlink()
        folder.rmdir()


def frame_w():
    from fastapi.testclient import TestClient

    from backend.app import create_app
    os.environ.update(PIPELINE="0", READ_ONLY="0")
    c = TestClient(create_app())
    r = c.get("/api/cameras/cam1/frame", params={"w": 480})
    expect(r.status_code == 200 and r.headers["content-type"] == "image/jpeg", f"status {r.status_code}")
    expect(decode(r.content).shape[1] == 480, f"width {decode(r.content).shape[1]}")
    expect(c.get("/api/cameras/cam1/frame", params={"w": 100}).status_code == 422, "w=100 accepted")


if __name__ == "__main__":
    check("read_only", read_only)
    check("blur", blur)
    check("blur_no_kpts", blur_no_kpts)
    check("max_streams", max_streams)
    check("demo_config", demo_config)
    check("stream_resolve", stream_resolve)
    check("remote_hosts", remote_hosts)
    check("shared_mjpeg", shared_mjpeg)
    check("stream_fps", stream_fps)
    check("stream_sync", stream_sync)
    check("blur_new_person", blur_new_person)
    check("admin_local", admin_local)
    check("cameras_base", cameras_base)
    check("events_keep", events_keep)
    check("frame_w", frame_w)
    sys.exit(1 if failed else 0)
