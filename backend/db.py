"""База событий SQLite."""
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from core.schemas import Event

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    type TEXT NOT NULL,
    severity TEXT NOT NULL,
    track_id INTEGER,
    bbox TEXT,
    conf REAL,
    ts_start REAL,
    ts_confirm REAL,
    ts_end REAL NULL,
    zone_id TEXT NULL,
    extra TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    comment TEXT NULL,
    snapshot TEXT
);
CREATE INDEX IF NOT EXISTS events_ts_confirm ON events (ts_confirm);
CREATE INDEX IF NOT EXISTS events_camera_id ON events (camera_id);
CREATE INDEX IF NOT EXISTS events_type ON events (type);
CREATE INDEX IF NOT EXISTS events_status ON events (status);
"""

FILTERS = ("type", "camera_id", "zone_id", "status", "severity")


def _row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["bbox"] = json.loads(d["bbox"]) if d["bbox"] else []
    d["extra"] = json.loads(d["extra"]) if d["extra"] else {}
    return d


class EventDB:
    def __init__(self, path: str):
        if path != ":memory:":
            p = Path(path)
            if not p.is_absolute():
                p = ROOT / p
            p.parent.mkdir(parents=True, exist_ok=True)
            path = str(p)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def insert(self, event: Event, snapshot: str) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO events (id, camera_id, type, severity, track_id, bbox, conf, ts_start, ts_confirm,"
                " ts_end, zone_id, extra, snapshot) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event.id, event.camera_id, event.type, event.severity, event.track_id,
                 json.dumps(list(event.bbox)), event.conf, event.ts_start, event.ts_confirm, event.ts_end,
                 event.zone_id, json.dumps(event.extra, ensure_ascii=False), snapshot),
            )
            self.conn.commit()

    def close(self, event_id: str, ts_end: float) -> None:
        with self.lock:
            self.conn.execute("UPDATE events SET ts_end = ? WHERE id = ?", (ts_end, event_id))
            self.conn.commit()

    def set_status(self, event_id: str, status: str, comment: str | None) -> bool:
        with self.lock:
            cur = self.conn.execute("UPDATE events SET status = ?, comment = ? WHERE id = ?",
                                    (status, comment, event_id))
            self.conn.commit()
            return cur.rowcount > 0

    def get(self, event_id: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return _row(row) if row else None

    @staticmethod
    def _where(filters: dict, ts_from: float | None, ts_to: float | None) -> tuple[str, list]:
        clauses, args = [], []
        for name in FILTERS:
            if filters.get(name) is not None:
                clauses.append(f"{name} = ?")
                args.append(filters[name])
        if ts_from is not None:
            clauses.append("ts_confirm >= ?")
            args.append(ts_from)
        if ts_to is not None:
            clauses.append("ts_confirm <= ?")
            args.append(ts_to)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", args

    def query(self, type=None, camera_id=None, zone_id=None, status=None, severity=None,
              ts_from=None, ts_to=None, limit=50, offset=0) -> tuple[list[dict], int]:
        filters = {"type": type, "camera_id": camera_id, "zone_id": zone_id, "status": status, "severity": severity}
        where, args = self._where(filters, ts_from, ts_to)
        with self.lock:
            total = self.conn.execute(f"SELECT COUNT(*) FROM events{where}", args).fetchone()[0]
            rows = self.conn.execute(f"SELECT * FROM events{where} ORDER BY ts_confirm DESC LIMIT ? OFFSET ?",
                                     [*args, limit, offset]).fetchall()
        return [_row(r) for r in rows], total

    def stats(self, ts_from: float | None = None, ts_to: float | None = None) -> dict:
        where, args = self._where({}, ts_from, ts_to)
        with self.lock:
            rows = self.conn.execute(f"SELECT type, camera_id, severity, status, ts_confirm FROM events{where}",
                                     args).fetchall()
        result = {"total": len(rows), "by_type": {}, "by_camera": {}, "by_severity": {}, "by_status": {},
                  "by_hour": [0] * 24, "by_day": {}}
        for r in rows:
            for key, value in (("by_type", r["type"]), ("by_camera", r["camera_id"]),
                               ("by_severity", r["severity"]), ("by_status", r["status"])):
                result[key][value] = result[key].get(value, 0) + 1
            dt = datetime.fromtimestamp(r["ts_confirm"])
            result["by_hour"][dt.hour] += 1
            day = dt.strftime("%Y-%m-%d")
            result["by_day"][day] = result["by_day"].get(day, 0) + 1
        result["by_day"] = dict(sorted(result["by_day"].items()))
        return result

    def close_open(self, ts: float) -> int:
        # ts_end неизвестен: событие было открыто при остановке сервиса, берётся момент тревоги
        with self.lock:
            cur = self.conn.execute("UPDATE events SET ts_end = ts_confirm WHERE ts_end IS NULL")
            self.conn.commit()
            return cur.rowcount
