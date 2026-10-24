"""Проверка реальных событий: пайплайн, база, снимки, API и WebSocket. python scripts/check_events.py."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
DB_PATH = str(Path(tempfile.mkdtemp(prefix="check_events_")) / "events.sqlite3")
os.environ["DB_PATH"] = DB_PATH
os.environ["PIPELINE"] = "1"
os.environ["DETECTOR_BACKEND"] = "onnx"

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import create_app  # noqa: E402
from backend.db import EventDB  # noqa: E402

WAIT = 25.0
EVENT_VIEW_KEYS = {
    "id", "camera_id", "camera_name", "type", "title", "severity", "track_id", "bbox", "conf",
    "ts_start", "ts_confirm", "ts_end", "zone_id", "zone_name", "extra", "status", "comment",
    "snapshot_url", "clip_url",
}

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


class Listener:
    """Читает /ws/events в отдельном потоке и складывает сообщения."""

    def __init__(self, client: TestClient):
        self.client = client
        self.messages: list[tuple[float, dict]] = []
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.connected = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.connected.wait(5)

    def _run(self):
        with self.client.websocket_connect("/ws/events") as ws:
            self.connected.set()
            while not self.stopped.is_set():
                msg = ws.receive_json()
                with self.lock:
                    self.messages.append((time.time(), msg))

    def find(self, pred, timeout: float):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                for _, msg in self.messages:
                    if pred(msg):
                        return msg
            time.sleep(0.1)
        return None

    def all(self) -> list[dict]:
        with self.lock:
            return [m for _, m in self.messages]


def main() -> None:
    state = {}
    start = time.time()
    with TestClient(create_app()) as c:
        listener = Listener(c)

        def ws_new():
            msg = listener.find(lambda m: m["kind"] == "event_new" and m["event"]["type"] == "fall", WAIT)
            expect(msg is not None, f"no event_new fall in {WAIT:.0f} s")
            state["event"] = msg["event"]
            state["t_new"] = time.time() - start
            missing = EVENT_VIEW_KEYS - msg["event"].keys()
            expect(not missing, f"missing {sorted(missing)}")

        def snapshot():
            r = c.get(state["event"]["snapshot_url"])
            expect(r.status_code == 200, f"code {r.status_code}")
            expect(r.headers["content-type"] == "image/jpeg", r.headers["content-type"])
            expect(len(r.content) > 10_000, f"{len(r.content)} bytes")

        def events_api():
            body = c.get("/api/events", params={"type": "fall"}).json()
            expect(body["total"] >= 1, f"total {body['total']}")
            expect(any(e["id"] == state["event"]["id"] for e in body["items"]), "event not in items")

        def patch():
            event_id = state["event"]["id"]
            r = c.patch(f"/api/events/{event_id}", json={"status": "confirmed", "comment": "check"})
            expect(r.status_code == 200 and r.json()["status"] == "confirmed", f"code {r.status_code}")
            items = c.get("/api/events", params={"status": "confirmed"}).json()["items"]
            expect(any(e["id"] == event_id for e in items), "not in status=confirmed")

        def ws_update():
            event_id = state["event"]["id"]
            msg = listener.find(lambda m: m["kind"] == "event_update" and m["event"]["id"] == event_id, WAIT)
            expect(msg is not None, f"no event_update in {WAIT:.0f} s")

        def no_dupes():
            seen = set()
            for m in listener.all():
                if m["kind"] == "event_new" and m["event"]["type"] == "fall":
                    key = (m["event"]["camera_id"], m["event"]["track_id"])
                    expect(key not in seen, f"duplicate fall {key}")
                    seen.add(key)

        def stats():
            body = c.get("/api/stats").json()
            total = c.get("/api/events").json()["total"]
            expect(body["total"] == total, f"stats {body['total']} events {total}")
            expect(sum(body["by_type"].values()) == body["total"], "by_type sum")

        check("ws_new", ws_new)
        if "event" not in state:
            for name in ("snapshot", "events_api", "patch", "ws_update", "no_dupes", "stats", "persist"):
                check(name, lambda: expect(False, "no event from ws_new"))
            return
        check("snapshot", snapshot)
        check("events_api", events_api)
        check("patch", patch)
        check("ws_update", ws_update)
        check("no_dupes", no_dupes)
        check("stats", stats)
        # Разбудить поток слушателя рассылкой, чтобы он закрыл соединение
        listener.stopped.set()
        c.patch(f"/api/events/{state['event']['id']}", json={"status": "confirmed", "comment": "check"})
        listener.thread.join(5)

    def persist():
        event_id = state["event"]["id"]
        row = EventDB(DB_PATH).get(event_id)
        expect(row is not None, "event not in db")
        if row["ts_end"] is None:
            with TestClient(create_app()):
                pass
            row = EventDB(DB_PATH).get(event_id)
        expect(row["status"] == "confirmed", f"status {row['status']}")
        expect(row["ts_end"] is not None, "ts_end not set")

    check("persist", persist)
    print(f"first event_new fall after {state['t_new']:.1f} s")


if __name__ == "__main__":
    main()
    sys.exit(1 if failed else 0)
