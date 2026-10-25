#!/usr/bin/env bash
# Необязательно: модели onnx, сборка фронтенда и видео стенда уже в git и приходят с клоном.
# Скрипт копирует с Mac ml/weights/*.onnx и frontend/dist/ по SSH, например чтобы проверить новую сборку
# без коммита. Нужен SSH-ключ на Mac; для первого запуска не используется (deploy/README.md).
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
if ! ls ml/weights/*.onnx >/dev/null 2>&1; then
    echo "Нет ml/weights/*.onnx. Экспорт весов: ml/README.md, раздел «Веса»." >&2
    exit 1
fi

ssh "$HOST" "mkdir -p $APP/ml/weights $APP/frontend/dist"
rsync -av ml/weights/*.onnx "$HOST:$APP/ml/weights/"
rsync -av --delete frontend/dist/ "$HOST:$APP/frontend/dist/"
ssh "$HOST" "chown -R mosprom $APP && systemctl restart mosprom"
echo "Готово. Логи: ssh $HOST journalctl -u mosprom -f"
