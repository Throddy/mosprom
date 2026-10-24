"""Прогон видео набора для настройки против разметки, для подбора порогов в BE-11.

python scripts/eval_offline.py [--labels data/videos/test/labels.csv] [--videos data/videos/test] [--trace TYPE]
    [--only VIDEO]

Обходит все видео папки. Видео без строк в разметке — сцены без нарушений: любое событие на них ложное.

Официальные метрики считает ML-7 на контрольном наборе, этот скрипт их не заменяет.
"""
import argparse
import csv
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backend.cameras import load_cameras  # noqa: E402
from run_offline import TEST_CAMERAS, run_offline  # noqa: E402


VIDEO_SUFFIXES = {".mov", ".MOV", ".mp4", ".MP4"}


def overlaps(event, t_start: float, t_end: float) -> bool:
    return event.ts_start <= t_end and event.ts_end >= t_start


def trace(video: Path, camera_id: str, detector) -> None:
    """Покадрово для каждого person: ts, track_id, точка ног в долях кадра, высота бокса,
    скорость v по формуле running и отношение высот бокса h_last / h_first за окно running."""
    import cv2

    from logic import Engine
    from logic.geometry import bbox_height, foot_point
    from logic.rules import RULES
    from logic.rules.running import speed

    camera = next(c for c in load_cameras(TEST_CAMERAS) if c.id == camera_id)
    running_cfg = next((r for r in camera.rules if r.type == "running"), None)
    window = float(RULES["running"].param(running_cfg, "window")) if running_cfg else 1.0
    engine = Engine(camera)
    cap = cv2.VideoCapture(str(video))
    step = (cap.get(cv2.CAP_PROP_FPS) or 25.0) / camera.fps
    index, n, next_pos = 0, 0, 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index >= next_pos:
            ts = n / camera.fps
            h, w = frame.shape[:2]
            result = engine.process(ts, w, h, detector.infer([frame])[0])
            for track in result.tracks:
                if track.cls != "person":
                    continue
                state = engine.tracks[track.track_id]
                fx, fy = foot_point(state.bbox)
                points = [b for t, b, _ in state.history if t >= ts - window]
                v = speed(state, ts, window)
                ratio = bbox_height(points[-1]) / bbox_height(points[0]) if len(points) > 1 else None
                print(json.dumps({
                    "ts": round(ts, 1), "track_id": track.track_id,
                    "foot": [round(fx / w, 3), round(fy / h, 3)], "h": round(bbox_height(state.bbox), 1),
                    "v": None if v is None else round(v, 2),
                    "h_ratio": None if ratio is None else round(ratio, 2),
                }))
            n += 1
            next_pos += step
        index += 1
    cap.release()


def trace_proximity(video: Path, camera_id: str, detector) -> None:
    """Покадрово: люди (track_id, точка ног в долях кадра, высота бокса), техника (cls, track_id, бокс)
    и минимальное расстояние d_norm от точки ног до бокса техники в ростах человека. В конце сводка."""
    import cv2

    from logic import Engine
    from logic.geometry import bbox_height, foot_point
    from logic.rules.proximity import VEHICLES, point_to_box

    camera = next(c for c in load_cameras(TEST_CAMERAS) if c.id == camera_id)
    engine = Engine(camera)
    cap = cv2.VideoCapture(str(video))
    step = (cap.get(cv2.CAP_PROP_FPS) or 25.0) / camera.fps
    index, n, next_pos = 0, 0, 0.0
    frames_with = defaultdict(int)
    best = None  # (d_norm, ts)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index >= next_pos:
            ts = n / camera.fps
            h, w = frame.shape[:2]
            result = engine.process(ts, w, h, detector.infer([frame])[0])
            people = [t for t in result.tracks if t.cls == "person"]
            vehicles = [t for t in result.tracks if t.cls in VEHICLES]
            for cls in {v.cls for v in vehicles}:
                frames_with[cls] += 1
            if vehicles:
                frames_with["any"] += 1
            d_min = None
            for p in people:
                ph = bbox_height(p.bbox)
                if ph <= 0:
                    continue
                fx, fy = foot_point(p.bbox)
                for v in vehicles:
                    d = point_to_box(fx, fy, v.bbox) / ph
                    d_min = d if d_min is None else min(d_min, d)
            if d_min is not None and (best is None or d_min < best[0]):
                best = (d_min, ts)
            print(json.dumps({
                "ts": round(ts, 1),
                "people": [{"track_id": p.track_id, "foot": [round(foot_point(p.bbox)[0] / w, 3),
                                                             round(foot_point(p.bbox)[1] / h, 3)],
                            "h": round(bbox_height(p.bbox), 1)} for p in people],
                "vehicles": [{"cls": v.cls, "track_id": v.track_id, "bbox": [round(x) for x in v.bbox]}
                             for v in vehicles],
                "d_norm_min": None if d_min is None else round(d_min, 2),
            }))
            n += 1
            next_pos += step
        index += 1
    cap.release()
    share = {cls: round(cnt / n, 2) for cls, cnt in sorted(frames_with.items())} if n else {}
    print(json.dumps({"trace_proximity": video.name, "frames": n, "share_with_vehicle": share,
                      "d_norm_min": None if best is None else round(best[0], 2),
                      "d_norm_min_ts": None if best is None else round(best[1], 1)}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Прогон тестовых видео против разметки")
    parser.add_argument("--labels", default="data/videos/test/labels.csv")
    parser.add_argument("--videos", default="data/videos/test")
    parser.add_argument("--trace", metavar="TYPE",
                        help="покадровая трассировка: running — на видео этого типа, proximity — на камере test_proximity")
    parser.add_argument("--only", metavar="VIDEO", help="оценить одно видео из папки")
    args = parser.parse_args()

    test_ids = {c.id for c in load_cameras(TEST_CAMERAS)}
    with open(args.labels, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_video: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_video[row["video"]].append(row)
    videos = sorted(p.name for p in Path(args.videos).iterdir() if p.suffix in VIDEO_SUFFIXES)
    if args.only:
        videos = [v for v in videos if v == args.only]
        if not videos:
            print(f"eval_offline: видео {args.only} нет в {args.videos}", file=sys.stderr)
            return 2

    from ml import create_detector
    detector = create_detector()
    totals = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "delay": []})
    negatives = {"videos": 0, "seconds": 0.0, "events": defaultdict(int)}
    total_seconds = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        for video in videos:
            labels = by_video.get(video, [])
            stem = Path(video).stem
            if f"test_{stem}" in test_ids:
                camera_id = f"test_{stem}"
            elif labels:
                camera_id = f"test_{labels[0]['type']}"
            else:
                camera_id = "test_normal"
            if args.trace == "proximity" and camera_id == "test_proximity":
                trace_proximity(Path(args.videos) / video, camera_id, detector)
            elif args.trace and labels and labels[0]["type"] == args.trace:
                trace(Path(args.videos) / video, camera_id, detector)
            events, frames, _ = run_offline(str(Path(args.videos) / video), camera_id,
                                            str(Path(tmp) / f"{stem}.jsonl"), detector=detector)
            fps = next(c.fps for c in load_cameras(TEST_CAMERAS) if c.id == camera_id)
            seconds = frames / fps
            total_seconds += seconds
            if not labels:
                negatives["videos"] += 1
                negatives["seconds"] += seconds
                for e in events:
                    negatives["events"][e.type] += 1
            matched = set()
            tp = fn = 0
            for label in labels:
                t_start, t_end = float(label["t_start"]), float(label["t_end"])
                hit = next((e for e in events if e.id not in matched and e.type == label["type"]
                            and overlaps(e, t_start, t_end)), None)
                if hit is None:
                    fn += 1
                    totals[label["type"]]["fn"] += 1
                    continue
                matched.add(hit.id)
                tp += 1
                totals[label["type"]]["tp"] += 1
                totals[label["type"]]["delay"].append(round(hit.ts_confirm - t_start, 2))
            unmatched = [e for e in events if e.id not in matched]
            for e in unmatched:
                totals[e.type]["fp"] += 1
            print(json.dumps({
                "video": video,
                "camera": camera_id,
                "type": labels[0]["type"] if labels else None,
                "seconds": round(seconds, 1),
                "labels": [[float(lb["t_start"]), float(lb["t_end"])] for lb in labels],
                "events": [{"type": e.type, "ts_start": round(e.ts_start, 2), "ts_confirm": round(e.ts_confirm, 2),
                            "ts_end": round(e.ts_end, 2), "extra": e.extra} for e in events],
                "tp": tp, "fp": len(unmatched), "fn": fn,
            }, ensure_ascii=False))

    print("итог по типам:")
    for rule_type, t in sorted(totals.items()):
        print(json.dumps({"type": rule_type, "tp": t["tp"], "fp": t["fp"], "fn": t["fn"],
                          "delay_s": t["delay"]}, ensure_ascii=False))
    print(json.dumps({"negatives": {"videos": negatives["videos"], "seconds": round(negatives["seconds"], 1),
                                    "events": dict(sorted(negatives["events"].items()))}}, ensure_ascii=False))
    hours = total_seconds / 3600
    fp_all = sum(t["fp"] for t in totals.values())
    print(json.dumps({"fp_per_hour": {
        "seconds": round(total_seconds, 1),
        "all": round(fp_all / hours, 1) if hours else None,
        **{rule_type: round(t["fp"] / hours, 1) for rule_type, t in sorted(totals.items())},
    }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
