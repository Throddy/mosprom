# Погрузчики классами COCO

| Параметр | Значение |
|---|---|
| Источник | `data/videos/ext/forklift/forklift_01.mp4`, 3840×2160, 25 кадр/с, 304 кадра |
| Кадров проверено | 50, через равные промежутки |
| Детектор | `create_detector("onnx")`, `yolov8n`, `conf` 0.4, классы `car`, `truck`, `bus` |
| Кадров с `car`, `truck` или `bus` | 38 из 50, доля 0.76 |
| Объектов по классам | `truck` 39, `car` 0, `bus` 0 |
| Кадров по классам | `truck` 38 |
| Кадры с боксами | `data/videos/ml5/forklift_00.jpg`, `_12`, `_24`, `_37`, `_49` (в git не попадают) |

Команда:

```bash
.venv/bin/python notebooks/forklift_check.py --src data/videos/ext/forklift/forklift_01.mp4
```

Решение: погрузчики детектируются классами COCO, для `proximity` использовать `[car, truck, bus]`.
