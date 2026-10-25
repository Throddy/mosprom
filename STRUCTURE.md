# Структура репозитория

В дереве перечислены файлы, которые требует `CONTRACT.md`. Остальное устройство папки зоны её владелец выбирает сам.

```
.
├── README.md                Никитос   описание, запуск, архитектура, ссылки
├── CONTRACT.md              все       зоны и интерфейсы, правка по разделу 9
├── PLAN.md                  все       задачи, каждый правит свой раздел
├── STRUCTURE.md             Максим    этот файл
├── GIT.md                   Максим    порядок работы с git
├── requirements.txt         Максим    только строки -r на файлы зон
├── .env.example             Максим    переменные окружения без значений
├── .gitignore               Максим
│
├── core/                    Максим    общие типы, код из раздела 3 контракта
│   ├── __init__.py
│   ├── schemas.py
│   └── config.py
│
├── configs/
│   ├── cameras.yaml         Максим    камеры, зоны, правила
│   ├── cameras.demo.yaml    Максим    камеры демо-стенда: ролик, зона, трансляции
│   └── models.yaml          Аня       модели, пороги, размер входа
│
├── ml/                      Аня
│   ├── __init__.py          create_detector()
│   ├── requirements.txt
│   ├── README.md            модели, веса, путь до TPU, замеры
│   └── weights/             в git только yolov8n-pose.onnx, yolov8n.onnx, README.md, SHA256SUMS
│
├── logic/                   Максим    трекинг и движок правил
│   ├── __init__.py
│   └── rules/               одно правило = один модуль
│
├── backend/                 Максим
│   ├── __main__.py          python -m backend
│   ├── requirements.txt     зависимости core/, logic/, backend/, scripts/
│   ├── README.md            запуск, API, правила, добавление правила
│   └── media/               снимки событий, в git не попадает
│
├── frontend/                Никитос
│   ├── package.json
│   └── dist/                сборка, в git: пересобирается и коммитится с frontend/src/
│
├── scripts/                 Максим
│   ├── run_offline.py
│   └── smoke.py
│
├── deploy/                  Максим    развёртывание: install.sh, python_deps.sh, torch-cpu.txt, systemd, Caddy, локальное демо
│
├── notebooks/               Аня       работа на сервере LinQ
│
├── data/
│   ├── demo.mp4             Максим    10 с, до 10 МБ, для smoke.py
│   ├── videos/              Никитос   в git, видео до 95 МБ на файл
│   │   └── demo/            Максим    копии 720p для быстрого запуска и стенда
│   └── test_set/
│       └── labels.csv       Никитос   разметка тестовых видео
│
├── reports/                 Аня
│   ├── benchmarks.json
│   └── metrics.json
│
└── docs/
    └── presentation/        Никитос
```

Видео лежат в git, до 95 МБ на файл. Файлы больше 95 МБ перечислены в `.gitignore` и доступны по ссылке из `README.md`. Состав данных — `data/README.md`.

## `.gitignore`

```
.env
.venv/
__pycache__/
.ipynb_checkpoints/
node_modules/
ml/weights/*
backend/media/
backend/data/
configs/cameras.local.yaml
*.pt
*.onnx
*.tpu
*.pt2
*.ovpn
*.npy
.DS_Store
# CPU-демо: две модели ONNX и их описание хранятся в git
!ml/weights/yolov8n-pose.onnx
!ml/weights/yolov8n.onnx
!ml/weights/README.md
!ml/weights/SHA256SUMS
```
