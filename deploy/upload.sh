#!/usr/bin/env bash
# Загрузка на сервер файлов, которых нет в git: веса onnx, сборка фронтенда, пережатые видео.
# Запуск на Mac из корня репозитория: bash deploy/upload.sh <user@host>
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Использование: bash deploy/upload.sh <user@host>, например root@203.0.113.10" >&2
    exit 1
fi
HOST="$1"
APP=/opt/mosprom

if [ ! -f frontend/dist/index.html ]; then
    echo "Нет frontend/dist/index.html. Соберите фронтенд:" >&2
    echo "  npm --prefix frontend ci && npm --prefix frontend run build" >&2
    exit 1
fi
if [ ! -d data/videos/demo ]; then
    echo "Нет data/videos/demo/. Пережмите видео и соберите ролик:" >&2
    echo "  python scripts/transcode.py --src data/videos/dev --dst data/videos/demo" >&2
    echo "  python scripts/make_reel.py --dst data/videos/demo/reel.mp4 data/videos/demo/normal_sit_stand.mp4 data/videos/demo/fall.mp4 data/videos/demo/normal_sit_stand.mp4 data/videos/demo/proximity.mp4 data/videos/demo/normal_sit_stand.mp4 data/videos/demo/running.mp4" >&2
    exit 1
fi
if ! ls ml/weights/*.onnx >/dev/null 2>&1; then
    echo "Нет ml/weights/*.onnx. Экспорт весов: ml/README.md, раздел «Веса»." >&2
    exit 1
fi

ssh "$HOST" "mkdir -p $APP/ml/weights $APP/frontend/dist $APP/data/videos/demo"
rsync -av ml/weights/*.onnx "$HOST:$APP/ml/weights/"
rsync -av --delete frontend/dist/ "$HOST:$APP/frontend/dist/"
rsync -av data/videos/demo/ "$HOST:$APP/data/videos/demo/"
ssh "$HOST" "chown -R mosprom $APP && systemctl restart mosprom"
echo "Готово. Логи: ssh $HOST journalctl -u mosprom -f"
