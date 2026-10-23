# Структура репозитория

В дереве перечислены файлы, которые требует `CONTRACT.md`. Остальное устройство папки зоны её владелец выбирает сам.

```
.
├── README.md                Максим    запуск, архитектура, ссылки на README зон
├── CONTRACT.md              все       зоны и интерфейсы, правка по разделу 8
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
│   └── config.py            load_cameras(), save_cameras()
│
├── configs/
│   ├── cameras.yaml         Максим    камеры, зоны, правила
│   └── models.yaml          Аня       модели, пороги, размер входа
│
├── ml/                      Аня
│   ├── __init__.py          create_detector()
│   ├── requirements.txt
│   ├── README.md            модели, веса, путь до TPU, замеры
│   └── weights/             в git не попадает
│
├── logic/                   Никитос
│   ├── __init__.py          Engine, rule_specs()
│   ├── requirements.txt
│   └── README.md            правила, параметры, добавление нового правила
│
├── backend/                 Максим
│   ├── requirements.txt
│   └── media/               снимки и клипы событий, в git не попадает
│
├── frontend/                Максим
│
├── scripts/                 Максим
│   ├── run_offline.py
│   └── smoke.py
│
├── notebooks/               Аня       работа на сервере LinQ
│
├── data/
│   ├── demo.mp4             Максим    10 с, до 10 МБ, для smoke.py
│   ├── videos/              все       в git не попадает, хранится в общей папке
│   └── test_set/
│       └── labels.csv       Аня
│
├── reports/                 Аня
│   ├── benchmarks.json
│   └── metrics.json
│
└── docs/
    └── presentation/        Никитос
```

## `.gitignore`

```
.env
__pycache__/
.ipynb_checkpoints/
ml/weights/
backend/media/
data/videos/
*.pt
*.onnx
```
