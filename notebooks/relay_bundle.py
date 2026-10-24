import argparse
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_SIZE_MB = 100
# yolov8n.onnx нужен LinqDetector: из его метаданных читаются имена классов COCO.
WEIGHT_PATTERNS = ("*_tail.onnx", "yolov8n.onnx")


def bundle_files() -> list[Path]:
    sources = sorted((ROOT / "core").rglob("*.py"))
    sources += [p for p in sorted((ROOT / "ml").rglob("*.py")) if "__pycache__" not in p.parts]
    for pattern in WEIGHT_PATTERNS:
        sources += sorted((ROOT / "ml/weights").glob(pattern))
    return sources + [ROOT / "configs/models.yaml"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("~/linq/upload/relay.tgz").expanduser())
    parser.add_argument("--wheels", type=Path,
                        default=Path("~/linq/upload/relay/wheels").expanduser())
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    files = bundle_files()
    wheels = sorted(args.wheels.glob("*.whl")) if args.wheels.is_dir() else []
    with tarfile.open(args.out, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=str(path.relative_to(ROOT)))
        for wheel in wheels:
            archive.add(wheel, arcname=f"wheels/{wheel.name}")

    size_mb = args.out.stat().st_size / 2**20
    print(f"архив {args.out}: {size_mb:.1f} МБ, файлов кода и весов {len(files)}, "
          f"колёс {len(wheels)}")
    if size_mb >= MAX_SIZE_MB:
        sys.exit(f"архив больше {MAX_SIZE_MB} МБ")


if __name__ == "__main__":
    main()
