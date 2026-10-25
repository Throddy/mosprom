# Демо-стенд

Стенд по ссылке: ролик с нашими видео, зона у двери и публичные трансляции с производств. Режим «только просмотр», лица размываются (`BLUR_FACES=1`), не больше 30 одновременных видеопотоков. Настройки: `deploy/env.demo`, камеры: `configs/cameras.demo.yaml`.

Модели ONNX, сборка интерфейса и видео стенда хранятся в git: сервер получает всё из клона, перенос файлов с Mac не нужен. Репозиторий приватный, поэтому сервер получает код по отдельному ключу развёртывания (deploy key) только на чтение.

Ограничения, которые установка не снимает:

- массовый просмотр не проверен: при канале 100 Мбит/с поток камеры трансляции 1228×720 и 15 кадрах/с занимает около 57 Мбит/с (оценка по размеру одного кадра); для первой проверки одним зрителем — `--stream-fps 5`;
- `DETECTOR_WORKERS` и `TILED_WORKERS` подбираются замером на сервере (`backend/README.md`, раздел «Производительность»);
- известные находки не исправлены: размытие лиц берёт рамки последнего обработанного кадра, адрес варианта HLS не проверяется по `REMOTE_HOSTS`, подавление повторов может долго скрывать новое нарушение рядом с прежним.

Команды ниже выполняются в Termius под `root`.

## A. Проверка сервера

```bash
lsb_release -ds; uname -m; nproc; free -h; df -h /
id mosprom 2>/dev/null; ls -la /opt/mosprom 2>/dev/null | head; systemctl is-active mosprom caddy 2>/dev/null
ss -ltnp | grep -E ':(80|443|8000) ' || echo "порты 80, 443, 8000 свободны"
```

Ожидается Ubuntu 22.04, `x86_64`. Если `mosprom`, `/opt/mosprom` или сервисы уже есть, ничего не удалять: это повторная установка, перейти к разделу «Обновление».

В группе безопасности облака должны быть открыты входящие TCP 22, 80 и 443. Порт 8000 наружу не открывается.

## B. Доступ к приватному репозиторию

Пользователь `mosprom` получает код и запускает сервис. Ключ создаётся на сервере, приватная часть остаётся там.

```bash
apt-get update -q && apt-get install -y -q git openssh-client
id mosprom >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin mosprom
install -d -o mosprom -g mosprom -m 700 /home/mosprom/.ssh
[ -f /home/mosprom/.ssh/github_deploy ] || runuser -u mosprom -- ssh-keygen -t ed25519 -N "" -C "mosprom-deploy" -f /home/mosprom/.ssh/github_deploy
cat /home/mosprom/.ssh/github_deploy.pub
```

Пауза: в GitHub → репозиторий → Settings → Deploy keys → Add deploy key вставить выведенную строку `ssh-ed25519 …`. Флажок Allow write access не ставить.

Ключ для GitHub и проверка ключа сервера GitHub:

```bash
grep -q "github_deploy" /home/mosprom/.ssh/config 2>/dev/null || printf 'Host github.com\n    IdentityFile ~/.ssh/github_deploy\n    IdentitiesOnly yes\n' >> /home/mosprom/.ssh/config
chown mosprom:mosprom /home/mosprom/.ssh/config && chmod 600 /home/mosprom/.ssh/config
ssh-keyscan -t ed25519 github.com > /tmp/github_ed25519 && ssh-keygen -lf /tmp/github_ed25519
```

Отпечаток сверить со страницей «GitHub's SSH key fingerprints» (docs.github.com): для ED25519 — `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`. Только при совпадении:

```bash
cat /tmp/github_ed25519 >> /home/mosprom/.ssh/known_hosts && chown mosprom:mosprom /home/mosprom/.ssh/known_hosts
runuser -u mosprom -- ssh -T git@github.com
```

Ожидается `Hi Throddy/mosprom! You've successfully authenticated, but GitHub does not provide shell access.` (код выхода 1 — это нормально).

## C. Получение проверенного коммита

`<SHA>` — полный SHA проверенного коммита `main`.

```bash
install -d -o mosprom -g mosprom /opt/mosprom
runuser -u mosprom -- git clone git@github.com:Throddy/mosprom.git /opt/mosprom
runuser -u mosprom -- git -C /opt/mosprom checkout --detach <SHA>
runuser -u mosprom -- git -C /opt/mosprom rev-parse HEAD
python3 -I /opt/mosprom/scripts/check_distribution.py --cameras configs/cameras.demo.yaml
```

Ожидается тот же SHA и `комплект полный`. При ошибке комплекта остановиться.

## D. Установка и запуск

```bash
bash /opt/mosprom/deploy/install.sh --stream-fps 5 <домен>
```

Скрипт ставит пакеты (git, Python 3.10 venv, библиотеки OpenCV, ffmpeg, Caddy), окружение `.venv` (PyTorch без CUDA, первый раз 5–10 минут), создаёт `/opt/mosprom/.env` из `deploy/env.demo`, если файла нет (`--stream-fps 5` меняет `STREAM_FPS` только в создаваемом файле), настраивает systemd и Caddy и проверяет запуск. Код и `.env` не перезаписываются, база и снимки не удаляются.

| Код выхода | Значение |
|---|---|
| `0` | сервис, `127.0.0.1:8000/api/status`, сайт и ресурсы, HTTPS проверены |
| `1` | ошибка установки, комплекта, настроек `.env` или запуска; журнал: `journalctl -u mosprom -n 80 --no-pager` |
| `3` | приложение работает локально, HTTPS не подтверждён: порты 80 и 443, DNS, `journalctl -u caddy -n 80 --no-pager` |

## E. Проверка

```bash
systemctl is-active mosprom caddy
journalctl -u mosprom -n 40 --no-pager | grep -E "обработчик|ERROR|Traceback" || true
curl -s 127.0.0.1:8000/api/status | python3 -m json.tool | head -40
curl -s 127.0.0.1:8000/ | grep -o '<title>[^<]*</title>'
curl -sI https://<домен>/ | head -1
ss -ltn | grep ':8000 '
```

Ожидается: оба сервиса `active`; в журнале строки `обработчик detector-…`; в статусе `"backend": "onnx"` и камеры `online: true` с `fps` больше 0 через 20–60 с; `<title>СОКОЛ</title>`; `HTTP/2 200`; порт 8000 только на `127.0.0.1`.

Затем открыть `https://<домен>` с Mac и с телефона: видео камер, рамки и скелеты, лента тревог, журнал.

## Обновление

```bash
runuser -u mosprom -- git -C /opt/mosprom fetch origin
runuser -u mosprom -- git -C /opt/mosprom checkout --detach <новый SHA>
bash /opt/mosprom/deploy/install.sh <домен>
```

`.env` сохраняется. Новые переменные из `deploy/env.demo` переносить в `/opt/mosprom/.env` вручную, затем `systemctl restart mosprom`.

## Логи и перезапуск

```bash
journalctl -u mosprom -f
systemctl restart mosprom
```

## Необязательно: `deploy/upload.sh`

Копирует с Mac по SSH `ml/weights/*.onnx` и `frontend/dist/` и перезапускает сервис, например для проверки новой сборки без коммита. Нужен SSH-ключ на Mac; для установки выше не используется.

## Тот же стенд локально

```bash
set -a; source deploy/env.demo; set +a
.venv/bin/python -m backend
```

Открыть `http://127.0.0.1:8000`. Только локальные видео, без трансляций и `.env`: `bash scripts/start_demo.sh`.
