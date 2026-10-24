# Демо-стенд

Публичный стенд по ссылке: ролик с нашими видео, зона у двери и публичные трансляции с производств. Режим «только просмотр», лица размыты, не больше 30 одновременных видеопотоков. Настройки: `deploy/env.demo`, камеры: `configs/cameras.demo.yaml`.

## 1. Сервер

Арендовать VPS:

- Ubuntu 22.04 (в ней Python 3.10 по умолчанию);
- 4–8 vCPU, 8 ГБ памяти, GPU не нужен;
- открыты порты 80 и 443 (у многих хостеров они открыты по умолчанию; если есть «файрвол» или «группа безопасности», добавить правила для TCP 80 и 443).

Записать IP-адрес сервера и пароль или ключ для входа `root`.

## 2. Домен

Свой домен: создать запись `A` на IP сервера.

Без домена: адрес `<IP>.sslip.io`, например для `203.0.113.10` — `203.0.113.10.sslip.io`. Он сам указывает на IP, настраивать ничего не нужно. HTTPS-сертификат Caddy получит автоматически.

## 3. Подготовка на Mac

Из корня репозитория, после `.venv` и весов по `README.md`:

```bash
npm --prefix frontend ci && npm --prefix frontend run build
python scripts/transcode.py --src data/videos/dev --dst data/videos/demo
python scripts/make_reel.py --dst data/videos/demo/reel.mp4 data/videos/demo/normal_sit_stand.mp4 data/videos/demo/fall.mp4 data/videos/demo/normal_sit_stand.mp4 data/videos/demo/proximity.mp4 data/videos/demo/normal_sit_stand.mp4 data/videos/demo/running.mp4
```

Исходные видео лежат в `data/videos/dev/` (общая папка команды). Пережатые видео — в `data/videos/demo/`, в git они не попадают.

## 4. Установка на сервере

```bash
ssh root@<IP>
curl -fsSL https://raw.githubusercontent.com/Throddy/mosprom/main/deploy/install.sh -o install.sh
bash install.sh <домен>
```

Скрипт ставит пакеты и Caddy, создаёт пользователя `mosprom`, клонирует код в `/opt/mosprom`, ставит зависимости Python (около 5 минут) и включает сервисы. Если весов ещё нет, он напишет «Загрузите веса: deploy/upload.sh» — это нормально.

## 5. Загрузка весов, сайта и видео

На Mac из корня репозитория:

```bash
bash deploy/upload.sh root@<IP>
```

Скрипт копирует `ml/weights/*.onnx`, `frontend/dist/` и `data/videos/demo/` и перезапускает сервис.

## 6. Проверка

Открыть `https://<домен>` с телефона. Через 10–20 с камеры станут `online`, в ленте появятся тревоги ролика.

## 7. Обновление и логи

Обновить код: на сервере `bash install.sh <домен>` ещё раз. Если менялся фронтенд или видео — на Mac `bash deploy/upload.sh root@<IP>`.

Логи:

```bash
journalctl -u mosprom -f
```

Перезапуск: `systemctl restart mosprom`.

## 8. Тот же стенд локально, для записи демо-видео

```bash
set -a; source deploy/env.demo; set +a
.venv/bin/python -m backend
```

Открыть `http://127.0.0.1:8000`.
