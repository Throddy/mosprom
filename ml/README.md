# ML

Владелец: Аня.

## Веса

Веса `.pt` и файлы `.onnx` не хранятся в git. Они лежат в `ml/weights/` и создаются экспортом:

```bash
mkdir -p ml/weights
cd ml/weights
../../.venv/bin/python -c "from ultralytics import YOLO; YOLO('yolov8n-pose.pt').export(format='onnx', imgsz=640); YOLO('yolov8n.pt').export(format='onnx', imgsz=640)"
cd ../..
```
