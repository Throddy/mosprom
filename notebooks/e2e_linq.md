# Сквозной прогон видео → тревога на LinQ (ML-4d)

Сквозной прогон видео через детектор `linq` и правила до тревоги. Видео `data/videos/dev/fall.mov` (тогда лежало в `data/videos/test/`): 1920×1080, 30 кадров/с, 33.2 с, 996 кадров. Камера `cam2`: правило `fall`, `min_duration` 3.0 с. Начало падения по разметке ML-7: 6.5 с.

```bash
DETECTOR_BACKEND=onnx .venv/bin/python scripts/run_offline.py --video data/videos/test/fall.mov \
  --camera cam2 --out data/videos/eval/fall.jsonl
set -a; source .env; set +a
DETECTOR_BACKEND=linq .venv/bin/python scripts/run_offline.py --video data/videos/test/fall.mov \
  --camera cam2 --out data/videos/eval/fall_linq.jsonl --fps 3
```

| Бэкенд | Частота обработки | Событие | `ts_start` | `ts_confirm` | Задержка `ts_confirm − 6.5` | Кадров | Время прогона | Кадров/с |
|---|---|---|---|---|---|---|---|---|
| `onnx`, CPU Apple M4 (ML-7) | 10 кадров/с | `fall` | 9.00 с | 12.00 с | 5.50 с | 332 | 45.6 с | 7.28 |
| `linq`, TPU через ретранслятор, 8 процессов | 3 кадра/с | `fall` | 9.67 с | 12.67 с | 6.17 с | 100 | 423.7 с | 0.24 |

- Из задержки 3.0 с — проверка неподвижности (`min_duration`).
- Разница `ts_start` 0.67 с при шаге кадров 0.33 с на `linq` и 0.1 с на `onnx`.
- В `data/test_set/labels.csv` начало падения размечено как 7.0 с: задержка `onnx` 5.0 с, `linq` 5.67 с.
- Прогон `linq` в 12.8 раза медленнее длительности видео: 4.2 с на кадр при последовательной обработке кадров в `run_offline.py`.

Вывод для слайда: сквозной прогон на LinQ TPU обнаружил падение на тестовом видео, тревога через 6.2 с после начала падения (на CPU — 5.5 с), обработка через облачный стенд — 0.24 кадра/с.
