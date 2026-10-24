"""Smoke-тест: data/demo.mp4 через детектор onnx и правила камер cam1 и cam2. python scripts/smoke.py."""
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ml import create_detector  # noqa: E402
from run_offline import run_offline  # noqa: E402


def check() -> str | None:
    """Причина ошибки или None."""
    detector = create_detector("onnx")
    video = str(ROOT / "data" / "demo.mp4")
    with tempfile.TemporaryDirectory() as tmp:
        events, _, _ = run_offline(video, "cam1", str(Path(tmp) / "cam1.jsonl"), detector=detector)
        events2, _, _ = run_offline(video, "cam2", str(Path(tmp) / "cam2.jsonl"), detector=detector)
    counts = Counter(e.type for e in events)
    if counts["fall"] != 1 or counts["danger_zone"] != 1:
        return f"cam1 events {dict(counts)}, expected fall=1 danger_zone=1"
    if any(e.ts_end is None for e in events):
        return "event without ts_end"
    fall = next(e for e in events if e.type == "fall")
    if fall.ts_start < 3.0:
        return f"fall ts_start {fall.ts_start:.2f} < 3.0"
    counts2 = Counter(e.type for e in events2)
    if counts2["fall"] != 1 or counts2["running"] != 0:
        return f"cam2 events {dict(counts2)}, expected fall=1 running=0"
    return None


if __name__ == "__main__":
    try:
        reason = check()
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
    if reason:
        print(f"smoke: fail: {reason}")
        sys.exit(1)
    print("smoke: ok")
