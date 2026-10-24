"""Кадр видео на заданной секунде в JPEG: python scripts/extract_frame.py --video PATH --t SECONDS --out PATH."""
import argparse
import sys
from pathlib import Path

import cv2


def main() -> int:
    parser = argparse.ArgumentParser(description="Кадр видео на заданной секунде в JPEG")
    parser.add_argument("--video", required=True)
    parser.add_argument("--t", type=float, required=True, help="секунда от начала видео")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"extract_frame: видео не открывается: {args.video}", file=sys.stderr)
        return 2
    cap.set(cv2.CAP_PROP_POS_MSEC, args.t * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print(f"extract_frame: нет кадра на {args.t} с", file=sys.stderr)
        return 2
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(args.out, frame)
    h, w = frame.shape[:2]
    print(f"{args.out}: {w}x{h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
