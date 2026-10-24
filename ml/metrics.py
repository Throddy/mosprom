import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LABELS = ROOT / "data/test_set/labels.csv"
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv"}

Interval = tuple[float, float]
Key = tuple[str, str]


def repo_path(path: Path) -> str:
    """Путь относительно корня репозитория, если файл лежит внутри него."""
    resolved = path.resolve()
    return str(resolved.relative_to(ROOT)) if resolved.is_relative_to(ROOT) else str(path)


def video_duration(path: Path) -> float:
    capture = cv2.VideoCapture(str(path))
    frames, fps = capture.get(cv2.CAP_PROP_FRAME_COUNT), capture.get(cv2.CAP_PROP_FPS)
    capture.release()
    if not fps:
        raise SystemExit(f"не удалось прочитать fps видео {path}")
    return frames / fps


def load_labels(path: Path, types: set[str]) -> dict[Key, list[Interval]]:
    labels: dict[Key, list[Interval]] = defaultdict(list)
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["type"] in types:
                labels[(row["video"], row["type"])].append((float(row["t_start"]),
                                                            float(row["t_end"])))
    return labels


def load_events(path: Path, duration: float, types: set[str]) -> dict[str, list[Interval]]:
    """Интервалы событий в секундах от начала видео; у события остаётся последняя запись по id."""
    last = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        last[event["id"]] = event
    events: dict[str, list[Interval]] = defaultdict(list)
    for event in last.values():
        if event["type"] in types:
            end = event["ts_end"] if event["ts_end"] is not None else duration
            events[event["type"]].append((event["ts_start"], end))
    return events


def match(labels: list[Interval], events: list[Interval]) -> int:
    """Число пар один к одному, жадно по убыванию длительности пересечения."""
    overlaps = sorted(((min(l[1], e[1]) - max(l[0], e[0]), i, j)
                       for i, l in enumerate(labels) for j, e in enumerate(events)), reverse=True)
    used_labels, used_events, pairs = set(), set(), 0
    for overlap, i, j in overlaps:
        if overlap <= 0:
            break
        if i in used_labels or j in used_events:
            continue
        used_labels.add(i)
        used_events.add(j)
        pairs += 1
    return pairs


def rule_metrics(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 3), "recall": round(recall, 3)}


def evaluate(videos: list[Path], events_dir: Path, labels: dict[Key, list[Interval]],
             types: set[str]) -> tuple[dict[str, dict], dict[str, float]]:
    """Счётчики tp, fp, fn по типам и сводка по видео без нарушений выбранных типов."""
    counts = {t: {"tp": 0, "fp": 0, "fn": 0} for t in sorted(types)}
    clean = {"videos": 0, "alarms": 0, "seconds": 0.0}
    for video in videos:
        events_path = events_dir / f"{video.stem}.jsonl"
        if not events_path.exists():
            raise SystemExit(f"нет событий для {video.name}: {events_path}")
        duration = video_duration(video)
        events = load_events(events_path, duration, types)
        if not any((video.name, t) in labels for t in types):
            clean["videos"] += 1
            clean["alarms"] += sum(len(found) for found in events.values())
            clean["seconds"] += duration
        for t in types:
            truth, found = labels.get((video.name, t), []), events.get(t, [])
            pairs = match(truth, found)
            counts[t]["tp"] += pairs
            counts[t]["fp"] += len(found) - pairs
            counts[t]["fn"] += len(truth) - pairs
    return counts, clean


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--videos", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--types", nargs="+", help="типы нарушений; по умолчанию все из разметки")
    args = parser.parse_args()

    with args.labels.open(encoding="utf-8") as f:
        types = set(args.types or {row["type"] for row in csv.DictReader(f)})
    videos = sorted(p for p in args.videos.iterdir() if p.suffix.lower() in VIDEO_EXTS)
    counts, clean = evaluate(videos, args.events, load_labels(args.labels, types), types)

    rules = {t: rule_metrics(**c) for t, c in counts.items()}
    args.out.write_text(json.dumps({"test_set": repo_path(args.labels), "rules": rules},
                                   ensure_ascii=False, indent=2) + "\n")
    for t, m in rules.items():
        print(f"{t}: tp {m['tp']}, fp {m['fp']}, fn {m['fn']}, "
              f"precision {m['precision']}, recall {m['recall']}")
    print(f"видео без нарушений {', '.join(sorted(types))}: {clean['videos']}, "
          f"тревог на них {clean['alarms']}, длительность {clean['seconds']:.1f} с")


if __name__ == "__main__":
    main()
