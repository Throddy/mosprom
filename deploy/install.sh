#!/usr/bin/env bash
# Установка демо-стенда на Ubuntu 22.04 из уже полученного клона. Запуск от root из клона:
#   bash deploy/install.sh [--stream-fps N] <домен>
#
# Код не обновляется: ставится текущий checkout, его SHA печатается. Комплект (модели, сборка фронтенда, видео)
# проверяется до запуска сервиса. .env создаётся из deploy/env.demo только при отсутствии; --stream-fps задаёт
# STREAM_FPS только в создаваемом .env. Повторный запуск не трогает базу, снимки и .env.
# Коды выхода: 0 — сервис, локальный API, сайт и HTTPS проверены; 1 — ошибка установки или запуска;
# 3 — приложение работает локально, HTTPS не подтверждён.
set -euo pipefail

usage() {
    echo "Использование: bash deploy/install.sh [--stream-fps N] <домен>, например sokol.203.0.113.10.sslip.io" >&2
    exit 1
}
STREAM_FPS_ARG=""
DOMAIN=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --stream-fps) [ -n "${2:-}" ] || usage; STREAM_FPS_ARG="$2"; shift 2 ;;
        -*) usage ;;
        *) [ -z "$DOMAIN" ] || usage; DOMAIN="$1"; shift ;;
    esac
done
[ -n "$DOMAIN" ] || usage
if [ "$(id -u)" -ne 0 ]; then
    echo "Запустите от root: sudo bash deploy/install.sh $DOMAIN" >&2
    exit 1
fi

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER=mosprom
# Нейтральный каталог: python3 и git от root не берут файлы из каталога, доступного пользователю сервиса
cd /
if ! id "$APP_USER" >/dev/null 2>&1; then
    echo "Нет пользователя $APP_USER. Код получает он: deploy/README.md, этап B." >&2
    exit 1
fi
OWNER="$(stat -c %U "$APP")"
if [ "$OWNER" != "$APP_USER" ]; then
    echo "Владелец $APP — $OWNER, нужен $APP_USER (клон делает пользователь $APP_USER)." >&2
    exit 1
fi
as_app() { runuser -u "$APP_USER" -- "$@"; }

echo "== 1. Код: $APP"
SHA="$(as_app git -C "$APP" rev-parse HEAD)"
echo "Коммит: $SHA"
# Скрипты из клона выполняются от root: изменённые и лишние неигнорируемые файлы останавливают установку
if [ -n "$(as_app git -C "$APP" status --porcelain)" ]; then
    echo "В клоне изменённые или лишние файлы, установка остановлена:" >&2
    as_app git -C "$APP" status --short >&2
    exit 1
fi

echo "== 2. Комплект"
python3 -I "$APP/scripts/check_distribution.py" --cameras configs/cameras.demo.yaml

echo "== 3. Пакеты и Caddy"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git python3.10-venv libgl1 libglib2.0-0 ffmpeg curl \
    debian-keyring debian-archive-keyring apt-transport-https gnupg
if [ ! -f /usr/share/keyrings/caddy-stable-archive-keyring.gpg ]; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -q
fi
apt-get install -y -q caddy

echo "== 4. Окружение Python (первый раз около 5–10 минут)"
if [ ! -x "$APP/.venv/bin/python" ]; then
    as_app python3.10 -m venv "$APP/.venv"
fi
as_app bash "$APP/deploy/python_deps.sh" "$APP/.venv/bin/python"

echo "== 5. Настройки"
ENV_FILE="$APP/.env"
if [ -f "$ENV_FILE" ]; then
    echo "$ENV_FILE уже есть, не меняется"
else
    install -o "$APP_USER" -m 600 "$APP/deploy/env.demo" "$ENV_FILE"
    if [ -n "$STREAM_FPS_ARG" ]; then
        sed -i "s/^STREAM_FPS=.*/STREAM_FPS=$STREAM_FPS_ARG/" "$ENV_FILE"
    fi
    echo "$ENV_FILE создан из deploy/env.demo"
fi
setting() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2-; }
for key in PIPELINE DETECTOR_BACKEND READ_ONLY BLUR_FACES CAMERAS_BASE CAMERAS_PATH BACKEND_HOST BACKEND_PORT STREAM_FPS \
        MAX_STREAMS DETECTOR_WORKERS TILED_CAMERAS TILED_WORKERS; do
    echo "  $key=$(setting "$key")"
done
bad=""
[ "$(setting PIPELINE)" = "1" ] || bad="$bad PIPELINE=1"
[ "$(setting DETECTOR_BACKEND)" = "onnx" ] || bad="$bad DETECTOR_BACKEND=onnx"
[ "$(setting READ_ONLY)" = "1" ] || bad="$bad READ_ONLY=1"
[ "$(setting BLUR_FACES)" = "1" ] || bad="$bad BLUR_FACES=1"
# Камеры стенда: прежняя схема — CAMERAS_PATH=configs/cameras.demo.yaml; с BE-20 — базовый файл и файл правок
if ! { [ "$(setting CAMERAS_PATH)" = "configs/cameras.demo.yaml" ] \
        || { [ "$(setting CAMERAS_PATH)" = "configs/cameras.demo.local.yaml" ] \
             && [ "$(setting CAMERAS_BASE)" = "configs/cameras.demo.yaml" ]; }; }; then
    bad="$bad CAMERAS_PATH=configs/cameras.demo.yaml (или CAMERAS_PATH=configs/cameras.demo.local.yaml и CAMERAS_BASE=configs/cameras.demo.yaml)"
fi
[ "$(setting BACKEND_HOST)" = "127.0.0.1" ] || bad="$bad BACKEND_HOST=127.0.0.1"
[ "$(setting BACKEND_PORT)" = "8000" ] || bad="$bad BACKEND_PORT=8000"
if [ -n "$bad" ]; then
    echo "В $ENV_FILE нужно:$bad. Установка остановлена." >&2
    exit 1
fi
mkdir -p "$APP/backend/data" "$APP/backend/media"
chown "$APP_USER" "$APP/backend/data" "$APP/backend/media"

echo "== 6. Сервисы"
sed "s|/opt/mosprom|$APP|g" "$APP/deploy/mosprom.service" > /etc/systemd/system/mosprom.service
NEW_CADDY="$(sed "s|{\$DOMAIN}|$DOMAIN|" "$APP/deploy/Caddyfile")"
if [ -f /etc/caddy/Caddyfile ] && [ "$(cat /etc/caddy/Caddyfile)" != "$NEW_CADDY" ]; then
    BACKUP="/etc/caddy/Caddyfile.bak.$(date +%Y%m%d%H%M%S)"
    cp /etc/caddy/Caddyfile "$BACKUP"
    echo "Прежний Caddyfile сохранён: $BACKUP"
fi
printf '%s\n' "$NEW_CADDY" > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable mosprom caddy
RESTARTS0="$(systemctl show -p NRestarts --value mosprom 2>/dev/null || echo 0)"
systemctl restart mosprom

echo "== 7. Проверка приложения на 127.0.0.1:8000"
fail() {
    echo "ОШИБКА: $1" >&2
    echo "Журнал: journalctl -u mosprom -n 80 --no-pager" >&2
    exit 1
}
status=""
for _ in $(seq 1 60); do
    if ! systemctl is-active --quiet mosprom \
            && [ "$(systemctl show -p NRestarts --value mosprom)" -gt "$((${RESTARTS0:-0} + 3))" ]; then
        fail "сервис mosprom перезапускается"
    fi
    status="$(curl -fsS --max-time 5 http://127.0.0.1:8000/api/status 2>/dev/null || true)"
    [ -n "$status" ] && break
    sleep 2
done
[ -n "$status" ] || fail "нет ответа http://127.0.0.1:8000/api/status за 120 с"
echo "$status" | python3 -I -c '
import json, sys
s = json.load(sys.stdin)
cams = s.get("cameras", [])
print("  backend:", s.get("backend"), "detector:", s.get("detector"), "камер:", len(cams))
sys.exit(0 if s.get("backend") == "onnx" and cams else 1)' || fail "в /api/status нет детектора onnx или камер"
if ss -ltnH | awk '{print $4}' | grep -Eq '^(0\.0\.0\.0|\*|\[::\]):8000$'; then
    fail "порт 8000 открыт на всех интерфейсах"
fi
INDEX="$(curl -fsS --max-time 5 http://127.0.0.1:8000/ || true)"
echo "$INDEX" | grep -q '<div id="root">' || fail "сайт не отдаётся на /"
for asset in $(echo "$INDEX" | grep -oE '(src|href)="/assets/[^"]+"' | cut -d'"' -f2); do
    curl -fsS --max-time 5 -o /dev/null "http://127.0.0.1:8000$asset" || fail "нет ресурса $asset"
done
echo "  сайт и ресурсы отдаются"

echo "== 8. Caddy и HTTPS: https://$DOMAIN"
systemctl restart caddy
systemctl is-active --quiet caddy || fail "caddy не запустился: journalctl -u caddy -n 80 --no-pager"
echo "  DNS: $DOMAIN -> $(getent hosts "$DOMAIN" | awk '{print $1}' | head -1)"
https_ok=""
for _ in $(seq 1 30); do
    if curl -fsS --max-time 10 -o /dev/null "https://$DOMAIN/api/status" 2>/dev/null; then
        https_ok=1
        break
    fi
    sleep 4
done
echo
echo "Коммит: $SHA"
if [ -z "$https_ok" ]; then
    echo "Приложение работает локально, HTTPS не подтверждён за 120 с."
    echo "Проверить: порты 80 и 443 в группе безопасности, DNS домена, journalctl -u caddy -n 80 --no-pager"
    exit 3
fi
echo "Готово: https://$DOMAIN отвечает. Проверьте сайт в браузере."
