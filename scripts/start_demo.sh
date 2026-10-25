#!/usr/bin/env bash
# Локальное CPU-демо из клона: bash scripts/start_demo.sh [--port 8000]
#
# macOS и Ubuntu 22.04. Python 3.10, окружение .venv внутри клона, детектор onnx, камеры demo_reel и demo_zone
# на видео из репозитория (deploy/cameras.local-demo.yaml). Без LinQ, трансляций и Node.js.
# Сервер слушает 127.0.0.1. .env не читается и не меняется; база и изменения камер — в backend/data/demo/.
# Интернет нужен только для установки зависимостей при первом запуске.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PORT=8000
if [ "${1:-}" = "--port" ] && [ -n "${2:-}" ]; then
    PORT="$2"
fi

# 1. Python 3.10
PYTHON="${PYTHON:-python3.10}"
if ! command -v "$PYTHON" >/dev/null 2>&1 \
        || [ "$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')" != "3.10" ]; then
    echo "Нужен Python 3.10 ($PYTHON не найден или другой версии)." >&2
    echo "  macOS: установщик с python.org (3.10.x) или brew install python@3.10" >&2
    echo "  Ubuntu 22.04: sudo apt-get install -y python3.10 python3.10-venv" >&2
    echo "Другой интерпретатор: PYTHON=/путь/к/python3.10 bash scripts/start_demo.sh" >&2
    exit 1
fi

# 2. Комплект: модели, сборка фронтенда, видео
"$PYTHON" -I scripts/check_distribution.py --cameras deploy/cameras.local-demo.yaml

# 3. Системные библиотеки OpenCV на Linux
if [ "$(uname -s)" = "Linux" ]; then
    missing=""
    for lib in libGL.so.1 libgthread-2.0.so.0; do
        ldconfig -p 2>/dev/null | grep -q "$lib" || missing="$missing $lib"
    done
    if [ -n "$missing" ]; then
        echo "Нет системных библиотек:$missing" >&2
        echo "  sudo apt-get install -y libgl1 libglib2.0-0" >&2
        exit 1
    fi
fi

# 4. Окружение и зависимости: повторная установка, только если изменились файлы зависимостей
if [ ! -x .venv/bin/python ]; then
    echo "== Создаю .venv"
    "$PYTHON" -m venv .venv
fi
if [ "$(.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])')" != "3.10" ]; then
    echo "В .venv не Python 3.10. Удалите .venv или запустите из другого клона." >&2
    exit 1
fi
STAMP=.venv/.mosprom-deps
WANT="$(cat requirements.txt backend/requirements.txt ml/requirements.txt deploy/torch-cpu.txt \
        | "$PYTHON" -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
if [ "$(cat "$STAMP" 2>/dev/null)" != "$WANT" ]; then
    echo "== Устанавливаю зависимости Python (первый раз несколько минут, нужен интернет)"
    bash deploy/python_deps.sh .venv/bin/python
    echo "$WANT" > "$STAMP"
fi

# 5. Данные демо отдельно от основной базы
DATA=backend/data/demo
mkdir -p "$DATA"
[ -f "$DATA/cameras.yaml" ] || cp deploy/cameras.local-demo.yaml "$DATA/cameras.yaml"

# 6. Окружение сервера задаётся явно: LinQ, CAMERAS_PATH стенда и плитки из оболочки не наследуются
for name in $(env | grep -o '^LINQ_[A-Z_]*' || true); do
    unset "$name"
done
export PIPELINE=1 DETECTOR_BACKEND=onnx DETECTOR_WORKERS=1 TILED_CAMERAS= TILED_WORKERS=1 \
    CAMERAS_PATH="$DATA/cameras.yaml" DB_PATH="$DATA/events.sqlite3" \
    BACKEND_HOST=127.0.0.1 BACKEND_PORT="$PORT" READ_ONLY=0 BLUR_FACES=0 MAX_STREAMS=30 STREAM_FPS=15 \
    SOURCE_LOOP=1 REMOTE_HOSTS= LOG_LEVEL=INFO

echo "== Демо: http://127.0.0.1:$PORT  (остановка: Ctrl+C)"
exec .venv/bin/python -m backend
