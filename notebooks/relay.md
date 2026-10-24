# Ретранслятор LinQ на сервере Jupyter

Ретранслятор `python -m ml.relay` работает на сервере Jupyter, в одной сети с TPU. Mac отправляет ему JPEG кадра и получает детекции. Через VPN вместо тензоров 4.69 МБ и 1.79 МБ идёт JPEG до 640 px и JSON.

```
Mac:    create_detector("linq") → LinqRelayDetector → JPEG в очередь relay.<LINQ_LOGIN>.in
Сервер: python -m ml.relay → LinqDetector → JSON с детекциями в reply_to
```

## Протокол

| Параметр | Значение |
|---|---|
| Брокер | `LINQ_AMQP_HOST`, `LINQ_AMQP_PORT`, `LINQ_AMQP_USER`, `LINQ_AMQP_PASSWORD` |
| Очередь запросов | `relay.<LINQ_LOGIN>.in`, не durable, `prefetch_count = 1` |
| Запрос | JPEG, качество 90, длинная сторона не больше 640 px; свойства `reply_to`, `correlation_id` |
| Ответ | `{"detections": [{"cls", "conf", "bbox": [x1, y1, x2, y2], "kpts": [[x, y, c], ...] \| null}], "timing": {"pre", "tpu", "post"}}`, время в мс |
| Ошибка | `{"error": "текст"}` |
| Тайм-аут клиента | 10 с на кадр |

Координаты в ответе даны в пикселях уменьшенного кадра. `LinqRelayDetector` делит их на коэффициент уменьшения по каждой оси.

## Зависимости сервера

Проверка сервера: Python 3.11.6, `numpy 1.24.4`, `pika 1.4.4`, `protobuf 4.24.3`, `PyYAML 6.0.1`, `Pillow 10.1.0`; `tpu_pycloud_format` установлен. Нет `onnxruntime` и `opencv`.

| Пакет | Версия | Причина версии |
|---|---|---|
| `onnxruntime` | 1.19.2 | совместим с `numpy 1.24` |
| `opencv-python-headless` | 4.10.0.84 | совместим с `numpy 1.24` |

Колёса под `cp311` `manylinux_x86_64` лежат в архиве в папке `wheels/` и ставятся с `--no-deps`, чтобы не обновлять `numpy`.

## Архив

```bash
.venv/bin/python notebooks/relay_bundle.py
```

Результат: `~/linq/upload/relay.tgz`, 70.3 МБ. Содержимое: `core/*.py`, `ml/**/*.py`, `ml/weights/*_tail.onnx`, `ml/weights/yolov8n.onnx` (имена классов COCO для `LinqDetector`), `configs/models.yaml`, `wheels/`.

Файл `relay.env` в архив не входит: переменные с паролем брокера не передаются через архив. `relay.env` создаётся на сервере вручную.

## Запуск на сервере

1. Загрузить `~/linq/upload/relay.tgz` кнопкой ↑ в папку `examples`.
2. Выполнить ячейку в `example.ipynb`:

```
!mkdir -p ~/relay && tar -xzf relay.tgz -C ~/relay
!cd ~/relay && pip install --user --no-index --no-deps --find-links wheels onnxruntime==1.19.2 opencv-python-headless==4.10.0.84
```

3. Создать `~/relay/relay.env` в терминале Jupyter. Строки `LINQ_LOGIN` и `LINQ_AMQP_*` скопировать из `.env` на Mac, `LINQ_PASSWORD` не копировать:

```bash
cat > ~/relay/relay.env <<'EOF'
LINQ_LOGIN=<значение>
LINQ_AMQP_HOST=<значение>
LINQ_AMQP_PORT=<значение>
LINQ_AMQP_USER=<значение>
LINQ_AMQP_PASSWORD=<значение>
EOF
```

4. Запустить в терминале Jupyter:

```bash
cd ~/relay && set -a && . ./relay.env && set +a && nohup python -m ml.relay > relay.log 2>&1 &
tail -n 5 relay.log
```

Ожидаемая строка: `relay: очередь relay.<LINQ_LOGIN>.in, детектор yolov8n-pose tpu int8 + yolov8n tpu int8`. Раз в 100 кадров в `relay.log` пишется среднее `timing`.

5. Вкладку Jupyter держать открытой, иначе сервер может остановиться.

Остановка: `pkill -f "python -m ml.relay"`.

## Проверка

Ретранслятор, запущенный на Mac, `bus.jpg` 810×1080 через `LinqRelayDetector`: 4 объекта, как у `onnx` (`bus` 1, `person` 3), IoU с `onnx` 0.937–0.983, `kpts` формы `(17, 3)`, `infer([])` возвращает `[]`.

Ретранслятор на сервере Jupyter, потребитель очереди с 24.10 01:26:

| Проверка | Результат |
|---|---|
| `.venv/bin/python notebooks/check_detector.py --backend linq` | код 0; кадр 810×1080: `person` 3, `bus` 1; кадр 640×360: `person` 3 |
| `.venv/bin/python notebooks/compare_backends.py` | объектов `onnx` 46, `linq` 40; пар 40; IoU среднее 0.950, минимальное 0.892; без пары `onnx` 6, `linq` 0; смещение точек `person` 10.14 px |
| 20 кадров `data/videos/calib/` по одному | `infer` медиана 4277 мс, максимум 6849 мс, минимум 652 мс |

Цель «медиана `infer` не больше 500 мс» не достигнута.

## Задержка на кадр с Mac (pose и det)

| Способ | Через VPN | Время на кадр |
|---|---|---|
| Прямой вызов TPU (`LinqDetector` на Mac) | 2 запроса по 4.69 МБ и ответы 1.79 МБ и 2.8 МБ | 4–9 с; `check_detector.py`: 9.1 с |
| Ретранслятор | JPEG до 640 px и JSON | медиана 4.28 с, максимум 6.85 с, минимум 0.65 с |

Время внутри ретранслятора, среднее `server_timing` по 20 кадрам:

| Этап | Время |
|---|---|
| `pre`: препроцессинг кадра | 520.9 мс |
| `tpu`: запросы pose и det к TPU с сервера | 2956.5 мс |
| `post`: хвосты графа и NMS | 346.9 мс |

Запрос к TPU с сервера Jupyter занимает в среднем 3 с при расчёте на TPU 2–80 мс (`notebooks/compile.md`, поле `inference_time`).
