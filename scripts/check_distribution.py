"""Проверка комплекта CPU-демо до установки зависимостей: модели, сборка фронтенда, локальные видео камер.

python3 scripts/check_distribution.py [--cameras configs/cameras.demo.yaml ...]

Только стандартная библиотека Python 3.10: запускается до pip install. Ничего не скачивает и не обращается
к трансляциям. Код возврата 0 — комплект полный, 1 — список ошибок с путями.
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_YAML = ROOT / "configs" / "models.yaml"
SUMS = ROOT / "ml" / "weights" / "SHA256SUMS"
DIST = ROOT / "frontend" / "dist"
DEFAULT_CAMERAS = ["configs/cameras.yaml", "configs/cameras.demo.yaml", "deploy/cameras.local-demo.yaml"]
CPU_MODELS = ("pose", "det")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_paths() -> dict[str, str]:
    """weights моделей pose и det из configs/models.yaml: строки вида `  pose: {weights: ml/weights/x.onnx, ...`."""
    found = {}
    for line in MODELS_YAML.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(\w+):\s*\{\s*weights:\s*([^,}\s]+)", line)
        if m and m.group(1) in CPU_MODELS:
            found[m.group(1)] = m.group(2)
    return found


def check_models(errors: list[str]) -> list[str]:
    ok = []
    if not MODELS_YAML.is_file():
        errors.append(f"нет {rel(MODELS_YAML)}")
        return ok
    paths = model_paths()
    for name in CPU_MODELS:
        if name not in paths:
            errors.append(f"{rel(MODELS_YAML)}: нет weights для модели {name}")
    if not SUMS.is_file():
        errors.append(f"нет {rel(SUMS)}")
        return ok
    expected = {}
    for line in SUMS.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            expected[parts[1].lstrip("*")] = parts[0].lower()
    for name, weights in paths.items():
        path = ROOT / weights
        want = expected.get(path.name)
        if want is None:
            errors.append(f"{rel(SUMS)}: нет суммы для {path.name}")
        elif not path.is_file():
            errors.append(f"нет модели {name}: {rel(path)}")
        elif sha256(path) != want:
            errors.append(f"SHA-256 не совпадает: {rel(path)}")
        else:
            ok.append(f"модель {name}: {rel(path)}, {path.stat().st_size} байт, SHA-256 совпадает")
    return ok


def local_refs(text: str) -> set[str]:
    """Локальные адреса ресурсов: src/href в HTML, url() в CSS, строки "/assets/..." в JS."""
    refs = set(re.findall(r'(?:src|href)="(/[^"#?]*)', text))
    refs |= set(re.findall(r'url\(\s*["\']?(/[^"\')#?]+)', text))
    refs |= set(re.findall(r'["\'`](/assets/[^"\'`#?]+)', text))
    return refs


def check_dist(errors: list[str]) -> list[str]:
    index = DIST / "index.html"
    if not index.is_file():
        errors.append(f"нет сборки фронтенда: {rel(index)}")
        return []
    files = {index}
    pending = [index]
    while pending:
        current = pending.pop()
        if current.suffix not in (".html", ".css", ".js"):
            continue
        text = current.read_text(encoding="utf-8", errors="replace")
        if re.search(r"localhost:\d+|127\.0\.0\.1:\d+|:5173\b|:4173\b", text):
            errors.append(f"сборка ссылается на dev-сервер или localhost: {rel(current)}")
        for ref in local_refs(text):
            target = DIST / ref.lstrip("/")
            if not target.is_file():
                errors.append(f"нет ресурса сборки {ref}: {rel(target)} (ссылка из {rel(current)})")
            elif target not in files:
                files.add(target)
                pending.append(target)
    return [f"фронтенд: {rel(index)} и {len(files) - 1} ресурсов по ссылкам"]


def camera_sources(path: Path) -> list[tuple[str, str]]:
    """(id, source) камер из YAML камер проекта: строки `- id: ...` и `source: ...`."""
    out, camera_id = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*-\s*id:\s*(\S+)", line)
        if m and not line.startswith("      "):
            camera_id = m.group(1)
        m = re.match(r'\s*source:\s*"?([^"#\s]+)"?', line)
        if m and camera_id:
            out.append((camera_id, m.group(1)))
    return out


def check_videos(configs: list[str], errors: list[str]) -> list[str]:
    ok = []
    for cfg in configs:
        path = ROOT / cfg
        if not path.is_file():
            errors.append(f"нет конфигурации камер: {cfg}")
            continue
        local = 0
        for camera_id, source in camera_sources(path):
            if source.startswith(("rtsp://", "http://", "https://")):
                continue
            local += 1
            video = ROOT / source
            if not video.is_file() or video.stat().st_size == 0:
                errors.append(f"{cfg}: камера {camera_id}: нет видео {source}")
        ok.append(f"{cfg}: локальных источников {local}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка комплекта CPU-демо")
    parser.add_argument("--cameras", nargs="+", default=DEFAULT_CAMERAS,
                        help="конфигурации камер, пути от корня репозитория")
    args = parser.parse_args()
    errors: list[str] = []
    ok = check_models(errors) + check_dist(errors) + check_videos(args.cameras, errors)
    for line in ok:
        print(f"ok {line}")
    for line in errors:
        print(f"ошибка: {line}")
    if errors:
        print(f"комплект неполный: ошибок {len(errors)}")
        return 1
    print("комплект полный")
    return 0


if __name__ == "__main__":
    sys.exit(main())
