#!/usr/bin/env bash
# Установка и обновление демо-стенда на Ubuntu 22.04. Запуск от root: bash install.sh <домен>
# Повторный запуск обновляет код (git pull), зависимости и перезапускает сервис.
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Использование: bash install.sh <домен>, например 203.0.113.10.sslip.io" >&2
    exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "Запустите от root: sudo bash install.sh $1" >&2
    exit 1
fi

DOMAIN="$1"
REPO="https://github.com/Throddy/mosprom.git"
APP=/opt/mosprom
APP_USER=mosprom

echo "== 1. Пакеты и Caddy"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git python3.10-venv libgl1 libglib2.0-0 ffmpeg \
    debian-keyring debian-archive-keyring apt-transport-https curl gnupg
if [ ! -f /usr/share/keyrings/caddy-stable-archive-keyring.gpg ]; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -q
fi
apt-get install -y -q caddy

echo "== 2. Пользователь, код, окружение Python"
if ! id "$APP_USER" >/dev/null 2>&1; then
    useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi
mkdir -p "$APP"
chown "$APP_USER" "$APP"
if [ -d "$APP/.git" ]; then
    runuser -u "$APP_USER" -- git -C "$APP" pull --ff-only
else
    runuser -u "$APP_USER" -- git clone "$REPO" "$APP"
fi
if [ ! -x "$APP/.venv/bin/python" ]; then
    runuser -u "$APP_USER" -- python3.10 -m venv "$APP/.venv"
fi
runuser -u "$APP_USER" -- "$APP/.venv/bin/python" -m pip install -q --upgrade pip
runuser -u "$APP_USER" -- "$APP/.venv/bin/python" -m pip install -q -r "$APP/requirements.txt"

echo "== 3. Настройки стенда"
cp "$APP/deploy/env.demo" "$APP/.env"
chown -R "$APP_USER" "$APP"

echo "== 4. Сервисы"
cp "$APP/deploy/mosprom.service" /etc/systemd/system/mosprom.service
sed "s|{\$DOMAIN}|$DOMAIN|" "$APP/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable mosprom caddy
systemctl restart caddy

echo "== 5. Веса"
if ! ls "$APP"/ml/weights/*.onnx >/dev/null 2>&1; then
    echo "Загрузите веса: deploy/upload.sh"
    echo "Сервис mosprom не запущен, он запустится после deploy/upload.sh."
else
    systemctl restart mosprom
fi

echo "== Готово: https://$DOMAIN"
