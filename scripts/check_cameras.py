"""Проверка PUT /api/cameras: валидация, сохранение в CAMERAS_PATH, применение без перезапуска.

python scripts/check_cameras.py
"""
import copy
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="check_cameras_"))
os.environ["CAMERAS_PATH"] = str(TMP / "cameras.local.yaml")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import create_app  # noqa: E402

BASE = ROOT / "configs" / "cameras.yaml"
CAMERAS_PATH = Path(os.environ["CAMERAS_PATH"])

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


def camera(c: TestClient, camera_id: str) -> dict:
    return next(x for x in c.get("/api/cameras").json() if x["id"] == camera_id)


def part_a() -> None:
    os.environ["PIPELINE"] = "0"
    base_before = BASE.read_bytes()
    c = TestClient(create_app())
    new_polygon = [[0.2, 0.3], [0.6, 0.3], [0.6, 0.9], [0.2, 0.9]]

    def put_ok():
        cam = camera(c, "cam1")
        cam["name"] = "Check name"
        cam["zones"][0]["polygon"] = new_polygon
        r = c.put("/api/cameras/cam1", json=cam)
        expect(r.status_code == 200, f"code {r.status_code} {r.text[:200]}")
        got = camera(c, "cam1")
        expect(got["name"] == "Check name" and got["zones"][0]["polygon"] == new_polygon, f"get {got['name']}")
        expect(CAMERAS_PATH.exists() and "Check name" in CAMERAS_PATH.read_text(encoding="utf-8"), "file")

    def reload():
        got = camera(TestClient(create_app()), "cam1")
        expect(got["name"] == "Check name" and got["zones"][0]["polygon"] == new_polygon, f"get {got['name']}")

    def invalid():
        cam = camera(c, "cam1")
        before = CAMERAS_PATH.read_bytes()
        zone_id = cam["zones"][0]["id"]

        def with_zone_polygon(polygon):
            def f(x):
                x["zones"][0]["polygon"] = polygon
            return f

        def with_rule(**changes):
            def f(x):
                x["rules"][0].update(changes)
            return f

        def without_rule_zone(x):
            x["rules"][0]["zone"] = None

        def duplicate_zone(x):
            x["zones"].append({**x["zones"][0]})

        cases = {
            "fps 0": lambda x: x.update(fps=0),
            "fps 31": lambda x: x.update(fps=31),
            "polygon 2 points": with_zone_polygon([[0.1, 0.1], [0.5, 0.5]]),
            "coordinate 1.5": with_zone_polygon([[0.1, 0.1], [1.5, 0.1], [0.5, 0.5]]),
            "coordinate -0.1": with_zone_polygon([[0.1, 0.1], [-0.1, 0.1], [0.5, 0.5]]),
            "source /etc/passwd": lambda x: x.update(source="/etc/passwd"),
            "source ../x.mp4": lambda x: x.update(source="../x.mp4"),
            "source data/../../x.mp4": lambda x: x.update(source="data/../../x.mp4"),
            "source data/nope.mp4": lambda x: x.update(source="data/nope.mp4"),
            "unknown rule type": with_rule(type="nope"),
            "schedule 25:00": with_rule(schedule=["25:00", "06:00"]),
            "schedule 7:5": with_rule(schedule=["7:5", "12:00"]),
            "danger_zone without zone": without_rule_zone,
            "zone not in zones": with_rule(zone="nope"),
            "min_duration abc": with_rule(params={"min_duration": "abc"}),
            "min_duration -1": with_rule(params={"min_duration": -1}),
            "unknown param": with_rule(params={"nope": 1.0}),
            "duplicate zone id": duplicate_zone,
        }
        expect(cam["rules"][0]["type"] == "danger_zone" and cam["rules"][0]["zone"] == zone_id,
               "cam1 rules[0] must be danger_zone with zone")
        bad = []
        for name, change in cases.items():
            body = copy.deepcopy(cam)
            change(body)
            r = c.put("/api/cameras/cam1", json=body)
            if r.status_code != 422 or not isinstance(r.json().get("detail"), str):
                bad.append(f"{name}: {r.status_code}")
        expect(not bad, ", ".join(bad))
        expect(CAMERAS_PATH.read_bytes() == before, "file changed")

    def codes():
        cam = camera(c, "cam1")
        r = c.put("/api/cameras/nope", json={**cam, "id": "nope"})
        expect(r.status_code == 404, f"nope {r.status_code}")
        r = c.put("/api/cameras/cam1", json={**cam, "id": "cam2"})
        expect(r.status_code == 400, f"id mismatch {r.status_code}")

    def base_untouched():
        expect(BASE.read_bytes() == base_before, "configs/cameras.yaml changed")

    check("put_ok", put_ok)
    check("reload", reload)
    check("invalid", invalid)
    check("codes", codes)
    check("base_untouched", base_untouched)


def part_b() -> None:
    os.environ["PIPELINE"] = "1"
    os.environ["DETECTOR_BACKEND"] = "onnx"
    os.environ["DB_PATH"] = str(TMP / "events.sqlite3")
    os.environ["CAMERAS_PATH"] = str(TMP / "cameras.b.yaml")
    with TestClient(create_app()) as c:
        known = {r["type"] for r in c.get("/api/rules").json()}

        def cam2() -> dict:
            # В configs/cameras.yaml у cam2 есть running, его нет в реестре до BE-9: PUT такого правила даёт 422
            cam = camera(c, "cam2")
            cam["rules"] = [r for r in cam["rules"] if r["type"] in known]
            return cam

        def cam2_fps() -> float:
            return next(x for x in c.get("/api/status").json()["cameras"] if x["id"] == "cam2")["fps"]

        def apply_fps():
            time.sleep(5)
            before = cam2_fps()
            r = c.put("/api/cameras/cam2", json={**cam2(), "fps": 4})
            expect(r.status_code == 200, f"code {r.status_code} {r.text[:200]}")
            time.sleep(8)
            after = cam2_fps()
            expect(3 <= after <= 5, f"fps before {before}, after {after}")

        def apply_rule():
            cam = cam2()
            cam["rules"] = [r for r in cam["rules"] if r["type"] != "fall"]
            r = c.put("/api/cameras/cam2", json=cam)
            expect(r.status_code == 200, f"code {r.status_code} {r.text[:200]}")
            put_ts = time.time()
            time.sleep(15)
            falls = c.get("/api/events", params={"type": "fall", "from": put_ts, "limit": 500}).json()["items"]
            falls_cam2 = [e for e in falls if e["camera_id"] == "cam2"]
            falls_cam1 = [e for e in falls if e["camera_id"] == "cam1"]
            expect(not falls_cam2, f"{len(falls_cam2)} new fall on cam2")
            expect(falls_cam1, "no new fall on cam1")

        check("apply_fps", apply_fps)
        check("apply_rule", apply_rule)


if __name__ == "__main__":
    part_a()
    part_b()
    sys.exit(1 if failed else 0)
