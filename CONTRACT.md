# Контракт команды

Документ задаёт зоны ответственности и интерфейсы между ними. Внутри своей зоны участник пишет код как хочет. Всё, что видно снаружи зоны (имена файлов, сигнатуры, форматы данных, API), описано здесь и меняется только по разделу 9.

## 1. Участники и зоны

| Участник | Роль | Владеет |
|---|---|---|
| Аня | ML и LinQ | `ml/`, `configs/models.yaml`, `notebooks/`, `reports/` |
| Максим | Бэкенд, логика нарушений, интеграция | `backend/`, `logic/`, `core/`, `scripts/`, `configs/cameras.yaml`, `data/demo.mp4`, `STRUCTURE.md`, `GIT.md`, `.env.example`, `requirements.txt`, `.gitignore` |
| Никитос | Фронтенд и продукт | `frontend/`, `README.md`, `docs/`, `data/test_set/` |

Задачи участников:

- **Аня.** Выбирает модели, экспортирует их в ONNX, квантует и компилирует под TPU. Пишет пре- и постпроцессинг для TPU. Делает замеры: FPS, задержку, число потоков на одну плату. Считает точность на тестовом наборе.
- **Максим.** Отвечает за приём видео и кадров, трекинг и движок правил: каждое нарушение реализуется отдельным плагином. Делает фильтр «нарушение длится N секунд», подавление дублей, базу событий, API и WebSocket. Пока LinQ не готов, работает с детектором `onnx` на CPU.
- **Никитос.** Делает ленту тревог со статусами, журнал с фильтрами, разметку опасных зон на кадре, дашборд и страницу замеров LinQ. Отвечает за тестовые видео и их разметку, `README.md`, презентацию и запасное демо-видео.

Владелец отвечает за работу своей зоны и за выполнение своих пунктов контракта. Чужие файлы не правит. Ошибку в чужой зоне описывает в issue и назначает на владельца.

## 2. Интеграция

Интегратор: Максим. Структура репозитория описана в `STRUCTURE.md`, порядок работы с git в `GIT.md`.

- В `main` вливает только Максим.
- Ветки: `ml/<задача>`, `backend/<задача>`, `frontend/<задача>`.
- PR меняет файлы только в зоне автора. Исключение: PR контракта (раздел 9).
- Перед вливанием Максим запускает `python scripts/smoke.py`. Если тест падает, PR возвращается автору.
- Зависимости Python: `ml/requirements.txt` (Аня) и `backend/requirements.txt` (Максим, покрывает `core/`, `logic/`, `backend/`, `scripts/`). Корневой `requirements.txt` подключает их через `-r`. Зависимости фронтенда хранятся в `frontend/package.json`.
- Python 3.10. Веса моделей, программы TPU, видео, `.env`, `node_modules/` и `frontend/dist/` в git не попадают.

## 3. Общие типы: `core/schemas.py`

Файл ведёт Максим. Содержимое совпадает с кодом ниже. Все `ts` содержат unix-время в секундах (`float`).

```python
from dataclasses import dataclass, field
from typing import Protocol
import numpy as np

BBox = tuple[float, float, float, float]  # x1, y1, x2, y2 в пикселях исходного кадра

CLASSES = ("person", "car", "truck", "bus", "forklift", "phone")
SEVERITIES = ("critical", "high", "medium")

@dataclass
class Detection:
    cls: str                          # значение из CLASSES
    conf: float                       # 0..1
    bbox: BBox
    kpts: np.ndarray | None = None    # (17, 3): x, y, conf; порядок COCO; только для person

class Detector(Protocol):
    name: str                         # например "yolov8n-pose int8 linq"
    last_timing: dict[str, float]     # мс последнего infer(): "pre", "infer", "post"
    def infer(self, images: list[np.ndarray]) -> list[list[Detection]]: ...

@dataclass
class Zone:
    id: str
    name: str
    polygon: list[tuple[float, float]]    # x, y в долях кадра, 0..1

@dataclass
class RuleConfig:
    type: str                             # значение "type" из правил (раздел 5)
    enabled: bool = True
    zone: str | None = None               # Zone.id
    schedule: tuple[str, str] | None = None   # ("07:55", "12:00"), местное время
    params: dict = field(default_factory=dict)

@dataclass
class CameraConfig:
    id: str
    name: str
    source: str                           # файл, rtsp://... или папка с кадрами
    fps: float                            # частота обработки, кадр/с
    zones: list[Zone] = field(default_factory=list)
    rules: list[RuleConfig] = field(default_factory=list)

@dataclass
class Track:
    track_id: int
    cls: str
    bbox: BBox
    active: list[str] = field(default_factory=list)   # типы нарушений, идущих сейчас

@dataclass
class Event:
    id: str                    # uuid4().hex
    camera_id: str
    type: str
    severity: str              # значение из SEVERITIES
    track_id: int
    bbox: BBox                 # бокс нарушителя на снимке события
    conf: float
    ts_start: float            # начало нарушения
    ts_confirm: float          # нарушение длится min_duration; в этот момент уходит тревога
    ts_end: float | None = None    # None, пока нарушение продолжается
    zone_id: str | None = None
    extra: dict = field(default_factory=dict)   # данные правила для карточки события
```

## 4. ML: детектор (Аня → Максим)

```python
# ml/__init__.py
def create_detector(backend: str | None = None) -> Detector: ...
```

- `backend`: `"onnx"` (ONNX Runtime на CPU) или `"linq"` (LinQ TPU). При `None` значение берётся из переменной `DETECTOR_BACKEND`, по умолчанию `"onnx"`.
- Вход `infer()`: кадры BGR, `uint8`, форма `(H, W, 3)`, как отдаёт `cv2`. Размеры кадров могут различаться.
- Выход: список той же длины, что вход. Элемент `i` содержит детекции кадра `i`.
- Координаты `bbox` и `kpts` даны в пикселях исходного кадра. Letterbox, NMS и порог `conf` выполняет ML. Пороги хранятся в `configs/models.yaml`.
- На одних и тех же кадрах выходы `onnx` и `linq` совпадают: IoU боксов больше 0.9.
- Детектор может быть непотокобезопасным: backend вызывает `infer()` из одного потока.
- Ключи `LINQ_*` для `.env.example` Аня передаёт Максиму. Как получить веса и программы TPU, Аня пишет в `ml/README.md`.

## 5. Правила нарушений (Максим → Никитос)

Каждое правило — отдельный модуль в `logic/rules/`. Новое правило добавляется без изменений во фронтенде: формы строятся по описанию из `GET /api/rules`.

Формат описания правила:

```json
{
  "type": "proximity",
  "title": "Сближение с техникой",
  "severity": "critical",
  "needs_zone": false,
  "params": [
    {"name": "dist", "type": "float", "unit": "рост человека", "default": 1.0},
    {"name": "min_duration", "type": "float", "unit": "с", "default": 0.5}
  ]
}
```

Обязательные типы:

| `type` | Нарушение | Пункт кейса |
|---|---|---|
| `fall` | Падение и неподвижность | 07 |
| `danger_zone` | Человек в опасной зоне | 05 |
| `proximity` | Сближение человека с техникой | 02 |
| `running` | Бег в зоне работы техники | 01 |
| `phone` | Телефон при работе и в проходах | 03 |

Гарантии:

- Событие создаётся, только если нарушение длится не меньше `min_duration`.
- Одно нарушение одного человека даёт одно событие. Пока нарушение продолжается, повторных событий нет.
- Изменения зон и правил применяются без перезапуска сервиса.

## 6. API бэкенда (Максим → Никитос)

- Запуск: `python -m backend`, адрес `http://localhost:8000`.
- Формат JSON, кодировка UTF-8. Время передаётся как unix-время в секундах.
- Ошибка возвращается HTTP-кодом и телом `{"detail": "текст"}`.
- CORS открыт для любого источника.
- Сборка фронтенда из `frontend/dist/` раздаётся по `/`, снимки событий — по `/media/...`.
- До задачи BE-6 API отдаёт тестовые данные в тех же форматах.

| Метод и путь | Запрос | Ответ |
|---|---|---|
| `GET /api/status` | — | `Status` |
| `GET /api/cameras` | — | список `Camera` |
| `PUT /api/cameras/{id}` | `Camera` | `Camera`. Изменения сохраняются и применяются сразу |
| `GET /api/cameras/{id}/frame` | — | `image/jpeg`, последний кадр без разметки |
| `GET /api/cameras/{id}/stream` | — | MJPEG (`multipart/x-mixed-replace`), кадры с треками и зонами. Вставляется в `<img src>` |
| `GET /api/rules` | — | список описаний правил (раздел 5) |
| `GET /api/events` | `type`, `camera_id`, `zone_id`, `status`, `severity`, `from`, `to`, `limit` (50), `offset` | `{"items": [EventView], "total": int}`, сортировка по `ts_confirm` по убыванию |
| `PATCH /api/events/{id}` | `{"status": str, "comment": str \| null}` | `EventView` |
| `GET /api/stats` | `from`, `to` | `Stats` |
| `GET /api/benchmarks` | — | содержимое `reports/benchmarks.json` |
| `GET /api/metrics` | — | содержимое `reports/metrics.json` |
| `WS /ws/events` | — | поток `WsMessage` |

`Camera` совпадает с `CameraConfig` в JSON:

```json
{"id": "cam1", "name": "Склад, ряд 3", "source": "data/videos/warehouse.mp4", "fps": 10,
 "zones": [{"id": "forklift_lane", "name": "Проезд погрузчика",
            "polygon": [[0.10, 0.40], [0.55, 0.40], [0.55, 0.95], [0.10, 0.95]]}],
 "rules": [{"type": "danger_zone", "enabled": true, "zone": "forklift_lane",
            "schedule": ["07:55", "12:00"], "params": {"min_duration": 1.0}}]}
```

`EventView` содержит поля `Event` и дополнительные поля для интерфейса:

```json
{"id": "3f2a9c", "camera_id": "cam1", "camera_name": "Склад, ряд 3",
 "type": "fall", "title": "Падение и неподвижность", "severity": "critical",
 "track_id": 17, "bbox": [412.0, 220.0, 530.0, 610.0], "conf": 0.86,
 "ts_start": 1792828800.0, "ts_confirm": 1792828803.0, "ts_end": null,
 "zone_id": null, "zone_name": null, "extra": {},
 "status": "new", "comment": null,
 "snapshot_url": "/media/cam1/3f2a9c.jpg", "clip_url": null}
```

- `status` принимает значения `new`, `confirmed` (подтверждено), `false` (ложное), `forwarded` (передано мастеру).
- На снимке нарушитель уже выделен. `clip_url` может быть `null`.

`WsMessage`:

```json
{"kind": "event_new", "event": {}}
```

`kind = "event_new"` означает новую тревогу. `kind = "event_update"` означает закрытие события (`ts_end`) или смену статуса. В поле `event` передаётся `EventView`.

`Stats`:

```json
{"total": 0, "by_type": {"fall": 0}, "by_camera": {"cam1": 0},
 "by_severity": {"critical": 0}, "by_status": {"new": 0},
 "by_hour": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
 "by_day": {"2026-10-24": 0}}
```

В `by_hour` 24 значения: число событий по часу `ts_confirm` по местному времени.

`Status`:

```json
{"detector": "yolov8n-pose int8 linq", "backend": "linq",
 "cameras": [{"id": "cam1", "online": true, "fps": 9.8, "latency_ms": 85.0}]}
```

`latency_ms` — время от получения кадра до результата правил.

## 7. Скрипты (Максим)

- `python scripts/run_offline.py --video PATH --camera ID --out PATH` прогоняет видео через детектор и правила без сервера. Результат: JSONL, одна строка на `Event` (`dataclasses.asdict`). Поля `ts_*` считаются в секундах от начала видео. Используется Аней для метрик.
- `python scripts/smoke.py` прогоняет `data/demo.mp4` на бэкенде `onnx`. При успехе возвращает код 0.

## 8. Отчёты и данные

`reports/benchmarks.json` (Аня) содержит список замеров. Никитос строит по нему страницу замеров и калькулятор.

```json
[{"model": "yolov8n-pose", "backend": "linq", "device": "LinQ TPU, 1 плата",
  "precision": "int8", "input": 640, "streams": 4, "fps": 0.0,
  "latency_ms": {"pre": 0.0, "infer": 0.0, "post": 0.0, "total": 0.0},
  "measured_at": "2026-10-24T15:00:00+03:00"}]
```

- `fps` указывается суммарно по всем потокам замера.
- Калькулятор: число камер на одну плату = `floor(fps / fps_камеры)`, где берётся наибольший `fps` среди записей с `backend = "linq"`.

`reports/metrics.json` (Аня) содержит метрики по событиям на тестовом наборе:

```json
{"test_set": "data/test_set/labels.csv",
 "rules": {"fall": {"tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0}}}
```

`data/test_set/labels.csv` (Никитос) содержит разметку событий тестовых видео. Время указано в секундах от начала видео. Сами видео лежат в общей папке, ссылка приведена в `README.md`.

```
video,type,t_start,t_end
fall_01.mp4,fall,12.0,20.5
```

## 9. Изменение контракта

1. Автор открывает PR `contract: <что меняется>`, в котором правит `CONTRACT.md` и `core/`.
2. Двое других участников подтверждают PR (approve).
3. Максим вливает PR. До вливания все работают по текущей версии.

Добавить значение в `CLASSES` можно без этой процедуры: достаточно PR в `core/` с подтверждением Максима.

## 10. Оформление текста

Правила действуют для всех `.md`, PR, коммитов, отчётов и комментариев в коде.

- Документы, PR и коммиты пишутся на русском. Код, имена файлов и идентификаторы пишутся на английском.
- В тексте только факты, команды, пути и числа. Без вступлений, итоговых абзацев, оценочных слов и эмодзи.
- Перечисления оформляются списками и таблицами. Код, пути и команды оформляются как `код`.
- Коммит: `<зона>: <что сделано> (<ID задачи>)`, например `ml: экспорт yolov8n-pose в onnx (ML-1)`. Зоны: `ml`, `backend`, `frontend`, `contract`.
- PR: заголовок оформляется как коммит. Тело состоит из трёх пунктов: «Что», «Задача» (номер из `PLAN.md`), «Как проверено».
