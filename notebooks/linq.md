# LinQ TPU: SDK и API

Материалы лежат в `~/linq`. Сокращения источников:

| Код | Файл |
|---|---|
| `FW` | `~/linq/tpu_framework/tpu_framework.pdf`, tpu_framework 2026.9.45, страницы по нумерации документа |
| `README` | `~/linq/tpu_framework/README.txt` |
| `COMPILE` | `~/linq/tpu_framework/compile.py` |
| `PACKETS` | `~/linq/tpu_framework/packets/` |
| `API` | `~/linq/api/API/usage_example_python_api/usage_example_python_api/` (`README.txt`, `example_torch_resnet50.py`) |
| `NB` | `~/linq/example.ipynb`, пример из папки `examples` Jupyter |
| `ИНСТР` | `~/linq/LinQ/Инструкция_удаленному_сервису_инференса_сетей_LinQ_TPU.pdf`, с. 1 |
| `ПРОЦ` | `~/linq/LinQ/Процедура_подготовки_и_инференса_сетей_на_LinQ_TPU.pdf`, с. 1 |
| `VPN` | `~/linq/LinQ/Настройка OpenVPN Ubuntu v2.pdf`, с. 2 |

## Среда SDK

- ОС: GNU/Linux Ubuntu 18.04 LTS или новее. `FW`, гл. 2 «System requirements», с. 5.
- Архитектура: x86_64. Все бинарные колёса в `PACKETS` имеют суффикс `cp312-cp312-linux_x86_64`. Колёс для macOS и arm64 нет.
- Python: 3.12.11. `FW`, с. 5; `README`.
- Установка: `python -m venv venv`, `source venv/bin/activate`, `cd packets`, `pip install pip -U`, `pip install -r requirements.txt`. `README`.
- Состав `packets/requirements.txt`: 13 локальных колёс (`tpu_framework_bin-2026.9.45`, `tpu_compiler_bin-2026.9.493`, `dnn_quant_bin-2026.9.98` и другие), `onnxruntime==1.29.0`, `pytest==9.1.1`, `attrs==26.1.0`. `PACKETS`.

## Требования к ONNX

- Формат: ONNX `onnx.ModelProto` через встроенный конвертер ONNX → TF, либо TF `GraphDef`. `FW`, гл. 1 «Overview», с. 3.
- Форма входа: только статическая. Динамическая форма не поддерживается, фиксируется функцией `freeze_shapes()` с явным словарём `input_nodes`. `COMPILE`, раздел «Optimization».
- Batch: берётся из первой размерности входа и входит в имя программы (`_b<batch>_`). `COMPILE`, `format_compile_name`. В сквозном тесте `network.set_batch(1)`. `FW`, гл. 5, с. 30, строка 598.
- Входы, совпадающие с `initializer`, удаляются до оптимизации (`remove_initialized_inputs`). `COMPILE`.
- opset: неизвестно.
- Неподдерживаемые операции: явного списка нет, неизвестно. Для `yolov8n_pose` из списка поддерживаемых моделей хвост графа после узлов `/model.22/...` вынесен в постпроцессинг. `FW`, гл. 6 «Supported models», с. 35–36, сноска 6.

## Квантование и компиляция

Порядок вызовов по `COMPILE`:

1. `preliminary_model_conditioning(onnx_model)`, результат `<name>/<name>_opt.onnx`.
2. `RegularModel(model=onnx_model).calibrate_torch(calibration_data=calibration_dict)` даёт пороги. `RegularModel.dump_thresholds(<name>/thresholds.json, thresholds)` сохраняет их.
3. `regular_model.quantize(thresholds)`, затем `quant_model.save(file_dir=<name>, file_name="quant_<name>.qm.onnx")` и `quant_model.as_torch_graph(batch_size=batch).export_to_pt2(<name>/quant_<name>.pt2)`.
4. `QuantizedModel.load(...)`, `Network.from_quantized_model(quantized_model)`, `compiler.compile_(hardware_parameters=TPU_H1M, network=network, parameters=PRESET)`.
5. `TpuProgram.from_executable(executable, tensor_descriptions).to_file(path)`.

- Пресеты компилятора: `O1` безопасный по умолчанию, `O3` и `O5` оптимизированные. При ошибке компиляции с `O5` нужно перейти на `O1`. `FW`, гл. 4.3, с. 16–17; комментарий в `COMPILE`.
- Платформа: `TPU_H1M`, строка платформы `h1m`. `COMPILE`.
- Калибровочные данные: словарь `{имя входа: np.ndarray float32}`. Массив содержит препроцессированные тензоры кадров, склеенные по оси batch, форма `(N, C, H, W)`. `FW`, гл. 5, с. 24, строки 249–273; `FW`, гл. 4.2, с. 11. В `COMPILE` для примера используются случайные данные с пометкой, что нужны реальные кадры.
- Ключи калибровки: в сквозном тесте имена входов переводятся через `regular_model.anchors_mapping` перед `calibrate()`. `FW`, с. 27, строки 437–447. `COMPILE` передаёт исходные имена в `calibrate_torch()`.
- Дообучение порогов: `fine_tune_torch(thresholds, fine_tuning_data, fine_tuning_epochs, ...)`. `FW`, гл. 4.2, с. 13–14.
- Имя выходного файла: `<name>_b<batch>_<o1|o5>_h1m.tpu` в папке `<name>/` рядом со скриптом, где `<name>` — имя ONNX без расширения. `COMPILE`, `format_compile_name`, `save_dir`.
- Запуск: путь к модели задаёт константа `MODEL_PATH` в начале `COMPILE`. В `README` указана команда `python compile_onnx.py`, а файл называется `compile.py`.

## Вынос слоёв на CPU

- Механизм: `tpu_framework.get_sub_model(model, ordered_input_names, ordered_output_names)` вырезает подграф ONNX между заданными узлами. Начало графа компилируется под TPU, конец выполняется ONNX Runtime на CPU, выход первой части подаётся на вход второй. `FW`, гл. 8 «Sub model», с. 39–41.
- Узлы разреза для `yolov8n_pose`: `/model.22/Mul_6_output_0`, `/model.22/Concat_6_output_0`, `/model.22/Concat_5_output_0`, `/model.22/Sigmoid_1_output_0`, `/model.22/Concat_7_output_0`, `/model.22/Sigmoid_output_0`, `/model.22/dfl/conv/Conv_output_0`. `FW`, с. 36, сноска 6.
- Для детекторов YOLO других версий разрез проходит по `/model.21/Div_1_output_0`, `/model.21/Sub_1_output_0`, `/model.21/Sigmoid_output_0` (`yolo12m`). `FW`, с. 36, сноска 4. Узлы для `yolov8n` (detect) в документе не указаны: неизвестно.

## Загрузка программы на сервис

- Программа компилируется локально и загружается на удалённый сервис. `ПРОЦ`; `ИНСТР`.
- В Jupyter программа должна лежать в `/auto/cache/<LOGIN>`. Пример копирует её командой `! cp {PROGRAM} {PROGRAM_DIR}` из рабочей папки Jupyter. `NB`, ячейка [0]; `ИНСТР`.
- Загрузка файла в рабочую папку Jupyter: через интерфейс Jupyter. Другие способы: неизвестно.

## Вызов через API

- Транспорт: RabbitMQ, клиент `pika` (`pika.BlockingConnection`). Брокер `10.0.114.30`, порт `5672`, в подсети VPN `10.0.114.0/24`. Логин и пароль брокера заданы в `NB`, ячейка [1], в заметку не переносятся. `NB`, ячейки [1], [3]; `VPN`.
- Обмен `tpu.direct`, ключ маршрутизации входной очереди `input`. `NB`, ячейка [1].
- Очередь ответа создаёт клиент: `queue_declare(queue=<имя>, auto_delete=True)` и `queue_bind(exchange="tpu.direct", queue=<имя>, routing_key=<имя>)`. `NB`, ячейка [3].
- Запрос: `basic_publish(exchange="tpu.direct", routing_key="input", body=serialize(PyTask({<вход>: <тензор>})))` с заголовками:
  - `TARGET_URI_ATTR_NAME`: `file:///auto/cache/<LOGIN>/<программа>.tpu?raw=False`;
  - `RESPONSE_ROUTING_KEYS_ATTR_NAME`: JSON-список с именем очереди ответа;
  - `MESSAGE_ID_ATTR_NAME`: идентификатор задачи, `uuid4().hex`.

  Константы, `PyTask`, `serialize` и `deserialize` импортируются из `tpu_pycloud_format`. `NB`, ячейка [3].
- Ответ: `channel.consume(<очередь>, auto_ack=True, inactivity_timeout=1.0)`, проверка `MESSAGE_ID_ATTR_NAME`, затем `data, metadata, worker = deserialize(body)`. `data` — словарь `{имя выхода: np.ndarray}`. `worker` содержит `worker_pid`, `status_code`, `error_message`. Пустой `data` означает ошибку воркера. `NB`, ячейка [4].
- Формат тензоров: вход и выход в пользовательском формате float32, например вход `(1, 3, 224, 224)` и выход `(1, 1000)` для resnet50. Упаковку выполняет сервис (`raw=False`). `NB`, ячейка [1].
- Режим: асинхронный. Запрос публикуется в очередь, ответ приходит в очередь клиента, тайм-аут ожидания в примере 60 с. `NB`, ячейки [1], [3], [4].
- Пакет `tpu_pycloud_format`: в `~/linq` его нет, он установлен в окружении Jupyter. Источник пакета: неизвестно.
- Локальный API `pytpu` работает только на машине с устройством `/dev/tpu*`: `tpu.Device.list_devices()`, `Device.open()`, `device.load(<программа>)`, `program.inference()`, `inference.run({<вход>: <тензор>})`. Установка через `Installation_Guide.pdf`, которого в материалах нет. `API`; `FW`, гл. 7, с. 37–38.

## Переменные окружения

| Имя | Назначение | Есть в `.env` |
|---|---|---|
| `LINQ_LOGIN` | логин Jupyter, задаёт папку программ `/auto/cache/<LINQ_LOGIN>` | да |
| `LINQ_PASSWORD` | пароль Jupyter, вызовом API не используется | да |
| `LINQ_AMQP_HOST` | адрес брокера RabbitMQ | нет |
| `LINQ_AMQP_PORT` | порт брокера RabbitMQ | нет |
| `LINQ_AMQP_USER` | логин брокера RabbitMQ | нет |
| `LINQ_AMQP_PASSWORD` | пароль брокера RabbitMQ | нет |

## Проверка

- resnet50 в Jupyter (запуск Ани): работает, класс 257, ответ 0.67 с, `status_code=0`.
- `curl -sS -m 10 -o /dev/null -w "%{http_code}\n" http://hackathon.lin-q.ru/` при включённом VPN: `302`.
- TCP-подключение к `10.0.114.30:5672` с Mac при включённом VPN с раздельным туннелем: порт открыт.
- В `.venv` установлены пакеты, которые импортирует пример: `pika 1.4.4`, `pillow 12.3.0`, `numpy 2.2.6`. `pytpu` и `tpu_pycloud_format` вне сервера недоступны.
- `notebooks/linq_check.py` не выполнил вызов: в `.env` нет `LINQ_AMQP_HOST`, `LINQ_AMQP_PORT`, `LINQ_AMQP_USER`, `LINQ_AMQP_PASSWORD`, запуск завершается на импорте `tpu_pycloud_format`.
