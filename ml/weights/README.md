# Модели CPU-демо

Две модели ONNX для детектора `onnx` хранятся в git, чтобы демо запускалось из клона без экспорта. Остальные файлы этой папки (`.pt`, программы TPU, хвосты графа LinQ) в git не попадают.

| Файл | Назначение | Размер, байт | SHA-256 |
|---|---|---|---|
| `yolov8n-pose.onnx` | люди и 17 ключевых точек, `configs/models.yaml` → `pose` | 13 514 627 | `a817811b9ab2b8c4393c38e1c777e792b5159627687843c0346bd7043b8b7b18` |
| `yolov8n.onnx` | техника: `car`, `truck`, `bus`, `configs/models.yaml` → `det` | 12 851 106 | `71d967d829fde4ec8c06586439227ce9b9ef72b33d489c438beb9e3602e092b0` |

Контрольные суммы для `sha256sum -c`: `SHA256SUMS`. Их же сверяет `scripts/check_distribution.py`.

## Происхождение и лицензия

- Экспорт официальных весов Ultralytics `yolov8n-pose.pt` (COCO-Pose) и `yolov8n.pt` (COCO) командой из `ml/README.md`, раздел «Веса и ONNX»: ultralytics 8.4.184, opset 18, onnxslim, `imgsz` 640, batch 1, без NMS. Дата экспорта в метаданных моделей: 24.10.2026.
- Метаданные ONNX: `author: Ultralytics`, `license: AGPL-3.0 License (https://ultralytics.com/license)`. Модели распространяются на условиях AGPL-3.0 Ultralytics.
- Модели не дообучались и не изменялись после экспорта.

## Замена моделей

Новая модель меняет результаты правил и метрик. После замены обновить `SHA256SUMS`, таблицу выше и повторить `python scripts/smoke.py`. Файл больше 95 МБ в git не добавляется.
