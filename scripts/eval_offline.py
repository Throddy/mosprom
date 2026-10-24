"""Прогон видео набора для настройки против разметки, для подбора порогов в BE-11.

python scripts/eval_offline.py [--labels data/videos/test/labels.csv] [--videos data/videos/test]

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


def overlaps(event, t_start: float, t_end: float) -> bool:
    return event.ts_start <= t_end and event.ts_end >= t_start


def main() -> int:
    parser = argparse.ArgumentParser(description="Прогон тестовых видео против разметки")
    parser.add_argument("--labels", default="data/videos/test/labels.csv")
    parser.add_argument("--videos", default="data/videos/test")
    args = parser.parse_args()

    test_ids = {c.id for c in load_cameras(TEST_CAMERAS)}
    with open(args.labels, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_video: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_video[row["video"]].append(row)

    from ml import create_detector
    detector = create_detector()
    totals = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "delay": []})
    with tempfile.TemporaryDirectory() as tmp:
        for video, labels in by_video.items():
            stem = Path(video).stem
            camera_id = f"test_{stem}" if f"test_{stem}" in test_ids else f"test_{labels[0]['type']}"
            events, _, _ = run_offline(str(Path(args.videos) / video), camera_id, str(Path(tmp) / f"{stem}.jsonl"),
                                       detector=detector)
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
                "type": labels[0]["type"],
                "labels": [[float(lb["t_start"]), float(lb["t_end"])] for lb in labels],
                "events": [{"type": e.type, "ts_start": round(e.ts_start, 2), "ts_confirm": round(e.ts_confirm, 2),
                            "ts_end": round(e.ts_end, 2), "extra": e.extra} for e in events],
                "tp": tp, "fp": len(unmatched), "fn": fn,
            }, ensure_ascii=False))

    print("итог по типам:")
    for rule_type, t in sorted(totals.items()):
        print(json.dumps({"type": rule_type, "tp": t["tp"], "fp": t["fp"], "fn": t["fn"],
                          "delay_s": t["delay"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
