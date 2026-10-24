# ML

Владелец: Аня. Подробности: `notebooks/linq.md` (SDK и API LinQ), `notebooks/compile.md` (компиляция), `notebooks/relay.md` (ретранслятор), `notebooks/forklift.md` (погрузчики).

## Модели

| Модель | Объекты | Вход | Выход ONNX | `conf` | IoU NMS |
|---|---|---|---|---|---|
| `yolov8n-pose` | `person`, 17 точек COCO `(x, y, conf)` | `[1, 3, 640, 640]` | `[1, 56, 8400]` | 0.4 | 0.7 |
| `yolov8n` | `car`, `truck`, `bus` из 80 классов COCO | `[1, 3, 640, 640]` | `[1, 84, 8400]` | 0.4 | 0.7 |

- Пути к весам, пороги и классы: `configs/models.yaml`.
- Погрузчики детектируются классом `truck`: 38 кадров из 50, доля 0.76 (`notebooks/forklift.md`).

## Установка

```bash
uv python install 3.10
"$(uv python find 3.10)" -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

- `python@3.10` из Homebrew на macOS 26.1 не создаёт venv (`pyexpat`), поэтому Python 3.10 ставится через uv.
- Бэкенду `linq` нужен пакет `tpu_pycloud_format` 0.0.1 из окружения Jupyter. Его копия кладётся в `~/linq/pkgs` и подключается файлом `linq_pkgs.pth` в `site-packages` `.venv` со строкой пути к `~/linq/pkgs`.
- Бэкенду `linq` нужен VPN LinQ: маршрут к `10.0.114.0/24`.

## Веса и ONNX

Веса `.pt`, файлы `.onnx` и программы TPU не хранятся в git. Они лежат в `ml/weights/`.

```bash
mkdir -p ml/weights
cd ml/weights
../../.venv/bin/python -c "from ultralytics import YOLO; YOLO('yolov8n-pose.pt').export(format='onnx', imgsz=640); YOLO('yolov8n.pt').export(format='onnx', imgsz=640)"
cd ../..
```

Экспорт: ultralytics 8.4.184, opset 18, onnxslim, batch 1, без NMS.

| Файл | Создаётся |
|---|---|
| `yolov8n-pose.onnx`, `yolov8n.onnx` | экспорт выше |
| `yolov8n-pose_head_b1_o1_h1m.tpu`, `yolov8n_head_b1_o1_h1m.tpu` | компиляция SDK, раздел «LinQ» |
| `yolov8n-pose_tail.onnx`, `yolov8n_tail.onnx` | разрез графа при компиляции |

## LinQ: ONNX → программа TPU → API

1. Калибровочные кадры и тензоры: 250 кадров в `data/videos/calib/`.

```bash
.venv/bin/python notebooks/make_calib.py --src data/videos/ext --out data/videos/calib --tensors
```

2. SDK `tpu_framework 2026.9.45` работает только на Linux x86_64 с Python 3.12. Контейнер и установка из колёс в `~/linq/wheels`:

```bash
docker run -d --name linq-sdk --platform linux/amd64 \
  -v "$PWD":/repo -v "$HOME/linq":/linq -w /repo python:3.12-slim sleep infinity
docker exec -w /linq/tpu_framework/packets linq-sdk \
  pip install --no-index --find-links /linq/wheels -r requirements.txt
```

3. Квантование int8 и компиляция `TPU_H1M`, пресет `O1`. Граф разрезан: при квантовании полного графа общий масштаб выхода `output0` обнулял уверенности 17 ключевых точек. Свёрточная часть (голова графа) идёт на TPU в int8, декодирование DFL, сборка `output0` и NMS — на CPU. Узлы разреза соответствуют сноске 6 к `yolov8n_pose` в `tpu_framework.pdf`.

```bash
docker exec -w /tmp linq-sdk python /linq/tools/compile_tpu.py \
  --onnx /repo/ml/weights/yolov8n-pose.onnx --calib /repo/data/videos/calib \
  --work-dir /repo/ml/weights/linq/yolov8n-pose-cut --program-dir /repo/ml/weights --preset o1 \
  --cut /model.22/dfl/conv/Conv_output_0,/model.22/Sigmoid_output_0,/model.22/Sigmoid_1_output_0,/model.22/Mul_4_output_0
docker exec -w /tmp linq-sdk python /linq/tools/compile_tpu.py \
  --onnx /repo/ml/weights/yolov8n.onnx --calib /repo/data/videos/calib \
  --work-dir /repo/ml/weights/linq/yolov8n-cut --program-dir /repo/ml/weights --preset o1 \
  --cut /model.22/dfl/conv/Conv_output_0,/model.22/Sigmoid_output_0
cp ml/weights/linq/yolov8n-pose-cut/yolov8n-pose_tail.onnx ml/weights/linq/yolov8n-cut/yolov8n_tail.onnx ml/weights/
```

4. Загрузка программ через Jupyter: файл в рабочую папку, затем `! cp <программа>.tpu /auto/cache/<LOGIN>/`.
5. Вызов: RabbitMQ `10.0.114.30:5672`, обмен `tpu.direct`, очередь `input`, сериализация `tpu_pycloud_format`. Вход только float32 `(1, 3, 640, 640)`, упаковку выполняет сервис (`raw=False`).
6. Ретранслятор на сервере Jupyter: архив `.venv/bin/python notebooks/relay_bundle.py` → `~/linq/upload/relay.tgz`, запуск `python -m ml.relay` по `notebooks/relay.md`.

| Этап | Где выполняется |
|---|---|
| `preprocess`: letterbox 640, RGB, `/255` | CPU, `ml/prepost.py` |
| голова графа pose и det | TPU, int8 |
| хвост графа: DFL, сборка `output0` | CPU, ONNX Runtime |
| NMS, перевод координат в кадр | CPU, `ml/prepost.py` |

## Бэкенды детектора

| `DETECTOR_BACKEND` | Класс | Цепочка | `name` |
|---|---|---|---|
| `onnx` | `OnnxDetector` | ultralytics + ONNX Runtime CPU | `yolov8n-pose+yolov8n onnx cpu` |
| `linq` | `LinqRelayDetector` | JPEG до 640 px → ретранслятор `ml.relay` на сервере Jupyter → `LinqDetector` → TPU | `yolov8n-pose+yolov8n tpu int8 via relay` |

- `LinqDetector` (`ml/backends/linq.py`) вызывает TPU напрямую. Его используют ретранслятор и замер времени ускорителя.
- Проверка: `.venv/bin/python notebooks/check_detector.py --backend onnx` или `--backend linq`.
- Сравнение `linq` с `onnx`: `.venv/bin/python notebooks/compare_backends.py`, 20 кадров.

| `linq` | IoU пар, среднее / минимальное | Без пары `onnx` / `linq` |
|---|---|---|
| прямой вызов TPU | 0.953 / 0.909 | 3 из 46 / 2 |
| через ретранслятор | 0.950 / 0.892 | 6 из 46 / 0 |

## Переменные окружения

| Имя | Назначение |
|---|---|
| `DETECTOR_BACKEND` | бэкенд по умолчанию: `onnx` или `linq` |
| `LINQ_LOGIN` | логин Jupyter, папка программ `/auto/cache/<LINQ_LOGIN>`, очередь `relay.<LINQ_LOGIN>.in` |
| `LINQ_PASSWORD` | пароль Jupyter, кодом не используется |
| `LINQ_AMQP_HOST` | адрес брокера RabbitMQ |
| `LINQ_AMQP_PORT` | порт брокера RabbitMQ |
| `LINQ_AMQP_USER` | логин брокера RabbitMQ |
| `LINQ_AMQP_PASSWORD` | пароль брокера RabbitMQ |

## Замеры

`reports/benchmarks.json`, 24.10:

| Бэкенд | Условия | Потоков | Кадров/с | pre, мс | infer, мс | post, мс | total, мс |
|---|---|---|---|---|---|---|---|
| `onnx` | CPU Apple M4, fp32 | 1 | 8.448 | 2.2 | 114.4 | 1.2 | 118.4 |
| `onnx` | CPU Apple M4, fp32 | 2 | 8.073 | 2.6 | 119.2 | 1.4 | 123.9 |
| `onnx` | CPU Apple M4, fp32 | 4 | 8.394 | 2.2 | 115.1 | 1.3 | 119.1 |
| `onnx` | CPU Apple M4, fp32 | 8 | 8.736 | 1.7 | 111.1 | 1.1 | 114.5 |
| `linq` | TPU int8, ретранслятор, 8 процессов | 1 | 0.170 | 2.4 | 5883.9 | 0.4 | 5886.8 |
| `linq` | TPU int8, ретранслятор, 8 процессов | 2 | 0.576 | 2.4 | 1732.4 | 0.2 | 1735.0 |
| `linq` | TPU int8, ретранслятор, 8 процессов | 4 | 0.719 | 2.2 | 1389.5 | 0.1 | 1391.8 |
| `linq` | TPU int8, ретранслятор, 8 процессов | 8 | 0.802 | 2.1 | 1244.9 | 0.1 | 1247.0 |
| `linq` | TPU int8, ретранслятор, 8 процессов | 16 | 0.804 | 3.5 | 1240.3 | 0.1 | 1243.9 |
| `linq` | TPU int8, только время ускорителя | 1 | 10.983 | 0 | 91.1 | 0 | 91.1 |

Условия замера:

- `set -a; source .env; set +a; .venv/bin/python ml/bench.py`.
- Кадры: первые 100 из `data/videos/calib/`, из них 25 кадров 3840×2160 и 75 кадров 640×480.
- Каждая конфигурация: прогрев (`onnx` — 5 вызовов, `linq` — 32 вызова), затем вызовы в течение 30 с, кадры раздаются потокам по кругу.
- `linq`: Mac → VPN → ретранслятор на сервере Jupyter, 8 процессов → сервис RabbitMQ → TPU.
- `total` = 1000 / `fps`. При нескольких потоках кадры обрабатываются параллельно, поэтому `total` меньше задержки одного кадра. Задержка одного кадра `linq`: 5–10 с.
- `linq` через ретранслятор: 0.80 кадра/с при 8 процессах и 8–16 потоках, было 0.26 кадра/с при 1 процессе (`notebooks/relay.md`).
- Время ускорителя: 30 кадров через `LinqDetector`, сумма `inference_time` воркера по pose и det.
- Потоков по 10 кадров/с на одну плату по времени ускорителя: `floor(10.983 / 10) = 1`.

## Метрики

`reports/metrics.json` (ML-7), бэкенд `onnx`. Пороги правил подобраны на `data/videos/dev/` (BE-11, BE-11b), метрики посчитаны на независимых дублях в `data/videos/test/`. Разметка `data/videos/test/labels.csv`, после вливания PR #38 — `data/test_set/labels.csv`.

| Тип | Видео и камера | tp | fp | fn | precision | recall |
|---|---|---|---|---|---|---|
| `fall` | `fall_02.mov`, `test_fall` | 1 | 0 | 0 | 1.0 | 1.0 |
| `running` | `running_03.mov`, `test_running` | 0 | 0 | 1 | 0.0 | 0.0 |
| `danger_zone` | `danger_zone_02.mov`, `test_danger_zone_02` | 1 | 0 | 0 | 1.0 | 1.0 |

- Задержка тревоги `fall`: 3.3 с от начала падения (`ts_confirm` 10.3 с при начале разметки 7.0 с), из них 1.5 с — ожидание неподвижности (BE-11).
- Задержка тревоги `danger_zone`: 1.6 с от входа в зону (`ts_confirm` 9.6 с при начале разметки 8.0 с).
- Сцена без нарушений `normal_walking.MOV`, 7 с: 0 тревог на камере `test_normal` (`fall`, `running`, `proximity`) и на камере `test_fall` со всеми 4 правилами.
- `running_03.mov`: бег не обнаружен. Бегущий детектируется в начале бега (2.5 с, уверенность 0.88), а в фазе бега (кадры 3.5, 4.5 и 5.5 с) рамки нет: силуэт смазан, трек теряется, и правилу нечего измерять.
- `proximity` в контрольном наборе не размечен.

## Ограничения

- Задержка одного кадра `linq` 5–10 с при расчёте на TPU 91 мс. Запрос к TPU с сервера Jupyter занимает около 3 с: очередь `input` общая для всех команд, её обслуживают 16 воркеров.
- Пропускная способность `linq` с 8 процессами ретранслятора: 0.80 кадра/с.
- Сервис принимает вход только float32: 4.69 МБ на кадр для каждой модели.
- Метрики на контрольном наборе: по одному видео с нарушением для `fall`, `running` и `danger_zone` и одна сцена без нарушений. `proximity` не размечен.
- Расхождения `linq` и `onnx` приходятся на объекты с уверенностью 0.41–0.58 у порога 0.4.
- Смещение ключевых точек `linq` относительно `onnx` на кадрах 3840×2160: 9–10 px.
- Модели не дообучались. Погрузчик детектируется как `truck`.
- Ретранслятор работает, пока открыта вкладка Jupyter.
- Человек в беге (ML-12). На контрольном `running_03.mov` в фазе бега силуэт смазан, детектор теряет человека, и правило `running` не срабатывает. На видео настройки смаза нет: порог `conf` модели pose не меняет долю кадров с человеком (`notebooks/run_detection.py`, шаг 0.1 с на интервале бега):

| Видео `dev/`, интервал бега | `conf` | Доля кадров с человеком | Средняя уверенность лучшего `person` |
|---|---|---|---|
| `running.mov`, 7.5–12.5 с | 0.4 | 1.00 | 0.85 |
| `running.mov`, 7.5–12.5 с | 0.25 | 1.00 | 0.85 |
| `running.mov`, 7.5–12.5 с | 0.15 | 1.00 | 0.85 |
| `running.mov`, 7.5–12.5 с | 0.1 | 1.00 | 0.85 |
| `running_02.mov`, 7.0–12.0 с | 0.4 | 1.00 | 0.80 |
| `running_02.mov`, 7.0–12.0 с | 0.25 | 1.00 | 0.80 |
| `running_02.mov`, 7.0–12.0 с | 0.15 | 1.00 | 0.80 |
| `running_02.mov`, 7.0–12.0 с | 0.1 | 1.00 | 0.80 |

  Порог 0.1 проверен на 5 видео `dev/`: события те же, что при 0.4 (`fall` на `fall.mov`, `running` на `running.mov`, `danger_zone` на `danger_zone.mov`, 0 на `normal_sit_stand.mov`). На `running_02.mov` бег не найден при обоих порогах, хотя человек виден на всех кадрах. Условие приёмки не выполнено, `conf` остался 0.4. Контрольный набор не пересчитывался: `running` на `running_03.mov` — tp 0, fn 1 (ML-7).

## Использование ИИ

Раздел по п. 4.3 положения хакатона.

- Код ML-модуля прошёл ревью с помощью ИИ-ассистента Claude Code по заданиям команды.
- Решения команды: выбор моделей, контракт детектора, разрез графа для квантования, ретранслятор, параллельные запросы, методика замеров и метрик.
