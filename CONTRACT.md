# Контракт команды

Документ задаёт зоны ответственности и интерфейсы между ними. Внутри своей зоны участник пишет код как хочет. Всё, что видно снаружи зоны (имена файлов, сигнатуры, форматы данных), описано здесь и меняется только по разделу 8.

## 1. Участники и зоны

| Участник | Роль | Владеет |
|---|---|---|
| Аня | ML | `ml/`, `configs/models.yaml`, `notebooks/`, `data/test_set/`, `reports/` |
| Никитос | Логика | `logic/`, `docs/presentation/` |
| Максим | Бэкенд, фронтенд, интеграция | `backend/`, `frontend/`, `core/`, `scripts/`, `configs/cameras.yaml`, `data/demo.mp4`, `README.md`, `STRUCTURE.md`, `GIT.md`, `.env.example`, `requirements.txt`, `.gitignore` |

Владелец отвечает за работу своей зоны и за выполнение своих пунктов контракта. Чужие файлы не правит. Ошибку в чужой зоне описывает в issue и назначает на владельца.

## 2. Интеграция

Интегратор: Максим. Структура репозитория описана в `STRUCTURE.md`, порядок работы с git в `GIT.md`.

- Создаёт репозиторий и защищает `main`. В `main` вливает только он.
- Ветки: `ml/<задача>`, `logic/<задача>`, `backend/<задача>`.
- PR меняет файлы только в зоне автора. Исключение: PR контракта (раздел 8).
- Перед вливанием Максим запускает `python scripts/smoke.py`. Если тест падает, PR возвращается автору.
- Зависимости: каждая зона ведёт свой файл (`ml/requirements.txt`, `logic/requirements.txt`, `backend/requirements.txt`). Корневой `requirements.txt` подключает их через `-r`.
- Python 3.10. Веса моделей, программы TPU, видео и `.env` в git не попадают.

## 3. Общие типы: `core/schemas.py`

Файл создаёт Максим. Содержимое совпадает с кодом ниже. Все `ts` содержат unix-время в секундах (`float`).

```python
from dataclasses import dataclass, field
from typing import Protocol
import numpy as np

BBox = tuple[float, float, float, float]  # x1, y1, x2, y2 в пикселях исходного кадра

CLASSES = ("person", "car", "truck", "bus", "forklift")
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
    type: str                             # значение "type" из logic.rule_specs()
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
    id: str                    # uuid4().hex, создаёт logic
    camera_id: str
    type: str
    severity: str              # значение из SEVERITIES
    track_id: int
    bbox: BBox                 # бокс нарушителя на кадре текущего вызова process()
    conf: float
    ts_start: float            # начало нарушения
    ts_confirm: float          # нарушение длится min_duration; в этот момент уходит тревога
    ts_end: float | None = None    # None, пока нарушение продолжается
    zone_id: str | None = None
    extra: dict = field(default_factory=dict)   # данные правила для карточки события
```

## 4. ML: детектор

```python
# ml/__init__.py
def create_detector(backend: str | None = None) -> Detector: ...
```

- `backend`: `"ultra"` (ultralytics, для разработки), `"onnx"` (onnxruntime на CPU), `"linq"` (LinQ TPU через RabbitMQ). При `None` значение берётся из переменной `DETECTOR_BACKEND`.
- `onnx` и `linq` используют одинаковый пре- и постпроцессинг.
- Вход `infer()`: кадры BGR, `uint8`, форма `(H, W, 3)`, как отдаёт `cv2`. Размеры кадров могут различаться.
- Выход: список той же длины, что вход. Элемент `i` содержит детекции кадра `i`.
- Координаты `bbox` и `kpts` даны в пикселях исходного кадра. Letterbox, NMS и порог `conf` выполняет ML. Пороги хранятся в `configs/models.yaml`.
- Детектор может быть непотокобезопасным: backend вызывает `infer()` из одного потока.
- Ключи `LINQ_*` для `.env.example` ML передаёт Максиму. Как получить веса и программы TPU, ML пишет в `ml/README.md`.

## 5. Logic: движок нарушений

```python
# logic/__init__.py
class Engine:
    def __init__(self, cameras: list[CameraConfig]) -> None: ...
    def process(self, camera_id: str, ts: float, frame_size: tuple[int, int],
                detections: list[Detection]) -> list[Event]: ...
    def update_camera(self, camera: CameraConfig) -> None: ...
    def tracks(self, camera_id: str) -> list[Track]: ...

def rule_specs() -> list[dict]: ...
```

- `process()` вызывается для каждого обработанного кадра камеры в порядке возрастания `ts`. `frame_size` передаётся как `(width, height)`.
- `process()` возвращает только изменения: новое событие (`ts_end is None`) или закрытие выданного ранее (тот же `id`, `ts_end` заполнен). Backend сохраняет событие по `id`.
- Одно нарушение одного трека даёт одно событие. Событие создаётся, только если нарушение длится не меньше `min_duration`.
- `update_camera()` применяет новые зоны и правила без перезапуска. Треки камеры при этом сохраняются.
- `tracks()` возвращает текущие треки для отрисовки видео в UI.
- Новый тип нарушения добавляется модулем в `logic/`. Backend и frontend при этом не меняются: формы правил строятся по `rule_specs()`.

Формат элемента `rule_specs()`:

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

## 6. Backend: конфигурация и инструменты

`core/config.py`:

```python
def load_cameras(path: str) -> list[CameraConfig]: ...
def save_cameras(path: str, cameras: list[CameraConfig]) -> None: ...
```

Формат `configs/cameras.yaml`:

```yaml
cameras:
  - id: cam1
    name: Склад, ряд 3
    source: data/videos/warehouse.mp4
    fps: 10
    zones:
      - id: forklift_lane
        name: Проезд погрузчика
        polygon: [[0.10, 0.40], [0.55, 0.40], [0.55, 0.95], [0.10, 0.95]]
    rules:
      - type: danger_zone
        zone: forklift_lane
        schedule: ["07:55", "12:00"]
        params: {min_duration: 1.0}
      - type: fall
```

Скрипты:

- `python scripts/run_offline.py --video PATH --camera ID --out PATH` прогоняет видео через `create_detector()` и `Engine` без сервера. Результат: JSONL, одна строка на `Event` (`dataclasses.asdict`). Поля `ts_*` считаются в секундах от начала видео.
- `python scripts/smoke.py` прогоняет `data/demo.mp4` на бэкенде `ultra`. При успехе возвращает код 0.

## 7. Отчёты ML: `reports/`

`reports/benchmarks.json` содержит список замеров. Backend строит по нему страницу замеров и калькулятор нагрузки.

```json
[{"model": "yolov8n-pose", "backend": "linq", "precision": "int8", "input": 640,
  "streams": 4, "fps": 0.0,
  "latency_ms": {"pre": 0.0, "infer": 0.0, "post": 0.0, "total": 0.0},
  "measured_at": "2026-10-24T15:00:00+03:00"}]
```

`reports/metrics.json` содержит метрики по событиям на тестовом наборе:

```json
{"test_set": "data/test_set/labels.csv",
 "rules": {"fall": {"tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0}}}
```

`data/test_set/labels.csv` описывает разметку событий. Время указано в секундах от начала видео.

```
video,type,t_start,t_end
fall_01.mp4,fall,12.0,20.5
```

## 8. Изменение контракта

1. Автор открывает PR `contract: <что меняется>`, в котором правит `CONTRACT.md` и `core/`.
2. Двое других участников подтверждают PR (approve).
3. Максим вливает PR. До вливания все работают по текущей версии.

Добавить значение в `CLASSES` можно без этой процедуры: достаточно PR в `core/` с подтверждением Максима.

## 9. Оформление текста

Правила действуют для всех `.md`, PR, коммитов, отчётов и комментариев в коде.

- Документы, PR и коммиты пишутся на русском. Код, имена файлов и идентификаторы пишутся на английском.
- В тексте только факты, команды, пути и числа. Без вступлений, итоговых абзацев, оценочных слов и эмодзи.
- Перечисления оформляются списками и таблицами. Код, пути и команды оформляются как `код`.
- Коммит: `<зона>: <что сделано>`, например `ml: добавлен onnx-бэкенд`.
- PR: заголовок оформляется как коммит. Тело состоит из трёх пунктов: «Что», «Задача» (номер из `PLAN.md`), «Как проверено».
