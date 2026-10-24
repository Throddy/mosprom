"""Проверка API бэкенда на тестовых данных: python scripts/check_api.py."""
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["FIXTURE_WS_INTERVAL"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import create_app  # noqa: E402

EVENT_VIEW_KEYS = {
    "id", "camera_id", "camera_name", "type", "title", "severity", "track_id", "bbox", "conf",
    "ts_start", "ts_confirm", "ts_end", "zone_id", "zone_name", "extra", "status", "comment",
    "snapshot_url", "clip_url",
}

failed = False


def check(path: str, fn) -> None:
    global failed
    try:
        fn()
        print(f"ok {path}")
    except Exception as e:
        failed = True
        print(f"fail {path}: {e}")


def expect(cond: bool, reason: str) -> None:
    if not cond:
        raise AssertionError(reason)


def main(client: TestClient) -> None:
    def status():
        body = client.get("/api/status").json()
        expect({"detector", "backend", "cameras"} <= body.keys(), f"keys {sorted(body)}")

    def cameras():
        cams = client.get("/api/cameras").json()
        expect(len(cams) == 2, f"{len(cams)} cameras")
        cam1 = next(c for c in cams if c["id"] == "cam1")
        r = client.put("/api/cameras/cam1", json={**cam1, "name": "check"})
        expect(r.status_code == 200 and r.json()["name"] == "check", f"put {r.status_code}")
        again = next(c for c in client.get("/api/cameras").json() if c["id"] == "cam1")
        expect(again["name"] == "check", "name not saved")
        r = client.put("/api/cameras/cam1", json={**cam1, "id": "x"})
        expect(r.status_code == 400, f"id mismatch {r.status_code}")

    def frame():
        r = client.get("/api/cameras/cam1/frame")
        expect(r.status_code == 200, f"code {r.status_code}")
        expect(r.headers["content-type"] == "image/jpeg", r.headers["content-type"])
        expect(r.content[:2] == b"\xff\xd8", "not jpeg")
        r = client.get("/api/cameras/nope/frame")
        expect(r.status_code == 404 and "detail" in r.json(), f"nope {r.status_code}")

    def rules():
        body = client.get("/api/rules").json()
        expect(len(body) >= 1, f"{len(body)} rules")
        for rule in body:
            expect({"type", "title", "severity", "needs_zone", "params"} <= rule.keys(), f"keys {sorted(rule)}")

    def events():
        body = client.get("/api/events", params={"limit": 5}).json()
        items = body["items"]
        expect(len(items) == 5, f"{len(items)} items")
        expect(body["total"] >= 40, f"total {body['total']}")
        ts = [e["ts_confirm"] for e in items]
        expect(ts == sorted(ts, reverse=True), "not sorted")
        expect(EVENT_VIEW_KEYS <= items[0].keys(), f"missing {sorted(EVENT_VIEW_KEYS - items[0].keys())}")
        falls = client.get("/api/events", params={"type": "fall"}).json()["items"]
        expect(all(e["type"] == "fall" for e in falls), "type filter")
        r = client.get("/api/events", params={"limit": "abc"})
        expect(r.status_code == 422 and isinstance(r.json()["detail"], str), f"limit=abc {r.status_code}")

    def snapshot():
        url = client.get("/api/events", params={"limit": 1}).json()["items"][0]["snapshot_url"]
        r = client.get(url)
        expect(r.status_code == 200, f"code {r.status_code}")
        expect(r.headers["content-type"] == "image/jpeg", r.headers["content-type"])

    def patch():
        event_id = client.get("/api/events", params={"limit": 1}).json()["items"][0]["id"]
        r = client.patch(f"/api/events/{event_id}", json={"status": "confirmed", "comment": None})
        expect(r.status_code == 200 and r.json()["status"] == "confirmed", f"code {r.status_code}")
        r = client.patch(f"/api/events/{event_id}", json={"status": "bad", "comment": None})
        expect(r.status_code == 400, f"bad status {r.status_code}")

    def stats():
        body = client.get("/api/stats").json()
        expect(len(body["by_hour"]) == 24, f"by_hour {len(body['by_hour'])}")
        expect(sum(body["by_type"].values()) == body["total"], "by_type sum")

    def reports():
        expect(isinstance(client.get("/api/benchmarks").json(), list), "benchmarks not list")
        expect(isinstance(client.get("/api/metrics").json(), dict), "metrics not object")

    def ws():
        got = {}

        def receive():
            with client.websocket_connect("/ws/events") as conn:
                while True:
                    msg = conn.receive_json()
                    if msg.get("kind") == "event_new":
                        got["msg"] = msg
                        return

        thread = threading.Thread(target=receive, daemon=True)
        thread.start()
        thread.join(3)
        expect("msg" in got, "no event_new in 3 s")
        expect("id" in got["msg"]["event"], "no event.id")

    check("/api/status", status)
    check("/api/cameras", cameras)
    check("/api/cameras/{id}/frame", frame)
    check("/api/rules", rules)
    check("/api/events", events)
    check("/media/...", snapshot)
    check("PATCH /api/events/{id}", patch)
    check("/api/stats", stats)
    check("/api/benchmarks, /api/metrics", reports)
    check("/ws/events", ws)


if __name__ == "__main__":
    with TestClient(create_app()) as client:
        main(client)
    sys.exit(1 if failed else 0)
