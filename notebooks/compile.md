# Компиляция yolov8n-pose под LinQ TPU

Описание SDK и API, сокращения источников (`FW`): `notebooks/linq.md`.

## Окружение

| Параметр | Значение |
|---|---|
| Хост | macOS 26.1, Apple M4, Docker Desktop 29.8.2 |
| Контейнер | `python:3.12-slim`, `linux/amd64` (эмуляция x86_64, AVX2 есть), Python 3.12.15 |
| SDK | `tpu_framework_bin 2026.9.45`, `tpu_compiler_bin 2026.9.493`, `dnn_quant_bin 2026.9.98`, `onnx_direct_bin 2026.8.23`, `tpu_tlm_bin 2026.8.42` |
| Зависимости SDK | `torch 2.9.1+cpu`, `tensorflow 2.20.0`, `onnx 1.16.2`, `onnxruntime 1.29.0` |
| Модель | `ml/weights/yolov8n-pose.onnx`, ultralytics 8.4.184, opset 18, вход `images` `[1, 3, 640, 640]`, выход `output0` `[1, 56, 8400]` |

Образ Python 3.12, а не 3.10: колёса SDK собраны только под `cp312-cp312-linux_x86_64`.

## Команды

Контейнер (из корня репозитория). `<scratch>` — папка с колёсами зависимостей и скриптом `compile_tpu.py`:

```bash
docker run -d --name linq-sdk --platform linux/amd64 \
  -v "$PWD":/repo -v "$HOME/linq":/linq -v <scratch>:/scratch \
  -w /repo python:3.12-slim sleep infinity
```

Установка SDK. Список колёс Linux получен на Mac командой ниже, колёса скачаны заранее в `<scratch>/sdk/wheelhouse`, потому что через VPN скорость одного соединения около 50 КБ/с. `torch` и `torchvision` берутся в CPU-сборке.

```bash
.venv/bin/python -m pip install --dry-run --ignore-installed --report report.json --target _unused \
  --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 --platform linux_x86_64 \
  --python-version 3.12 --implementation cp --abi cp312 --only-binary=:all: \
  --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt  # пути к колёсам packets/ абсолютные
docker exec -w /linq/tpu_framework/packets linq-sdk \
  pip install --no-index --find-links /scratch/sdk/wheelhouse -r requirements.txt
```

Калибровочные данные: 250 кадров, 25 из `data/videos/ext/forklift/forklift_01.mp4` и 225 из `data/videos/ext/urfall/`, тензоры через `ml.prepost.preprocess`:

```bash
.venv/bin/python notebooks/make_calib.py --src data/videos/ext --out data/videos/calib --tensors
```

Компиляция головы графа (используемый вариант):

```bash
docker exec -w /tmp linq-sdk python /scratch/compile_tpu.py \
  --onnx /repo/ml/weights/yolov8n-pose.onnx --calib /repo/data/videos/calib \
  --work-dir /repo/ml/weights/linq/yolov8n-pose-cut --program-dir /repo/ml/weights --preset o1 \
  --cut /model.22/dfl/conv/Conv_output_0,/model.22/Sigmoid_output_0,/model.22/Sigmoid_1_output_0,/model.22/Mul_4_output_0
```

Скрипт `compile_tpu.py` повторяет `~/linq/tpu_framework/compile.py`: оптимизация, калибровка `calibrate_torch` на реальных кадрах, квантование, компиляция `TPU_H1M` с пресетом `O1`. Разрез графа выполняет `get_sub_model` (`FW`, гл. 8). Экспорт `.pt2` из `compile.py` не нужен для компиляции и пропущен.

```python
import argparse
import time
from pathlib import Path

import numpy as np
import onnx
from tpu_framework import (O1, O5, TPU_H1M, Network, QuantizedModel, RegularModel, TpuProgram,
                           compiler, get_sub_model, preliminary_model_conditioning)

PRESETS = {"o1": O1, "o5": O5}
PLATFORM = "h1m"


def remove_initialized_inputs(model: onnx.ModelProto) -> None:
    by_name = {i.name: i for i in model.graph.input}
    for init in model.graph.initializer:
        if init.name in by_name:
            model.graph.input.remove(by_name[init.name])


def static_inputs(model: onnx.ModelProto) -> dict[str, list[int]]:
    shapes = {i.name: [d.dim_value for d in i.type.tensor_type.shape.dim]
              for i in model.graph.input}
    for name, shape in shapes.items():
        if 0 in shape:
            raise SystemExit(f"динамическая форма входа {name}: {shape}")
    return shapes


def split(model: onnx.ModelProto, cut: list[str], out_dir: Path, name: str) -> onnx.ModelProto:
    inputs = [i.name for i in model.graph.input]
    outputs = [o.name for o in model.graph.output]
    tail = get_sub_model(model=model, ordered_input_names=cut, ordered_output_names=outputs)
    onnx.save(tail, out_dir / f"{name}_tail.onnx")
    head = get_sub_model(model=model, ordered_input_names=inputs, ordered_output_names=cut)
    onnx.save(head, out_dir / f"{name}_head.onnx")
    return head


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--calib", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--program-dir", type=Path, required=True)
    parser.add_argument("--preset", choices=sorted(PRESETS), default="o1")
    parser.add_argument("--cut", default="")
    args = parser.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    name = args.onnx.stem
    model = onnx.load(args.onnx)
    if args.cut:
        model = split(model, args.cut.split(","), args.work_dir, name)
        name = f"{name}_head"
    remove_initialized_inputs(model)
    static_inputs(model)

    started = time.monotonic()
    opt_path = args.work_dir / f"{name}_opt.onnx"
    onnx.save(preliminary_model_conditioning(model), opt_path)
    optimized = onnx.load(opt_path)
    shapes = static_inputs(optimized)
    input_name = next(iter(shapes))
    batch = shapes[input_name][0]
    print(f"1/3 оптимизация: {time.monotonic() - started:.0f} с, входы {shapes}", flush=True)

    files = sorted(args.calib.glob("*.npy"))
    calibration = {input_name: np.concatenate([np.load(f) for f in files], axis=0)}
    regular = RegularModel(model=optimized)
    thresholds = regular.calibrate_torch(calibration_data=calibration)
    RegularModel.dump_thresholds(str(args.work_dir / "thresholds.json"), thresholds)
    quant_name = f"quant_{name}.qm.onnx"
    regular.quantize(thresholds).save(file_dir=str(args.work_dir), file_name=quant_name)
    print(f"2/3 квантование: {time.monotonic() - started:.0f} с, кадров {len(files)}", flush=True)

    quantized = QuantizedModel.load(str(args.work_dir / quant_name))
    network, _ = Network.from_quantized_model(quantized)
    executable, descriptions = compiler.compile_(
        hardware_parameters=TPU_H1M, network=network, parameters=PRESETS[args.preset])
    program = args.program_dir / f"{name}_b{batch}_{args.preset}_{PLATFORM}.tpu"
    TpuProgram.from_executable(executable, descriptions).to_file(str(program))
    print(f"3/3 компиляция: {time.monotonic() - started:.0f} с", flush=True)
    for tensor_name, description in descriptions.items():
        print(f"тензор {tensor_name}: {description}")
    print(f"программа {program}, {program.stat().st_size / 2**20:.1f} МБ")


if __name__ == "__main__":
    main()
```

## Результат

| Вариант | Программа | Размер | Время (оптимизация + квантование + компиляция) | Входы и выходы программы |
|---|---|---|---|---|
| голова графа, используется | `ml/weights/yolov8n-pose_head_b1_o1_h1m.tpu` | 2.8 МБ | 99 с, из них квантование 52 с | `images`; `/model.22/dfl/conv/Conv_output_0` `[1, 1, 4, 8400]`, `/model.22/Sigmoid_output_0` `[1, 1, 8400]`, `/model.22/Sigmoid_1_output_0` `[1, 17, 1, 8400]`, `/model.22/Mul_4_output_0` `[1, 17, 2, 8400]` |
| полный граф, не используется | `ml/weights/yolov8n-pose_b1_o1_h1m.tpu` | 2.8 МБ | 107 с, из них квантование 58 с | `images`; `output0` `[1, 56, 8400]` |

- Точность квантования: int8, вход `images` с масштабом 127 (`ml/weights/linq/yolov8n-pose-cut/scales.json`).
- Компилятор принял все слои обоих вариантов, ошибок нет.

## Части графа на CPU

Начало графа до узлов разреза выполняется на TPU. Хвост `ml/weights/yolov8n-pose_tail.onnx` выполняется ONNX Runtime на CPU: 13 узлов (`Reshape`, `Slice`, `Sub`, `Add`, `Div`, `Mul`, `Concat`), декодирование боксов из DFL и сборка `output0` `[1, 56, 8400]`. Входы хвоста совпадают по именам и формам с выходами программы. Узлы разреза соответствуют сноске 6 к `yolov8n_pose` в `FW`, гл. 6, с. 36.

Полный граф не используется. После квантования единый выход `output0` получает общий масштаб для координат точек и их уверенностей. Уверенности всех 17 точек становятся 0, координаты точек идут шагом около 3 px.

Сравнение с исходным ONNX на 10 калибровочных кадрах. Квантованная модель исполнялась torch-графом SDK (`as_torch_graph` и `rescale`, как в `FW`, гл. 5), якоря с уверенностью выше 0.4:

| Метрика | Полный граф | Голова + хвост на CPU |
|---|---|---|
| IoU бокса с максимальной уверенностью | 0.85–0.95 | 0.93–0.99 |
| Средняя ошибка бокса | 2.1–4.4 px | 0.8–2.2 px |
| Средняя ошибка координат точек | 1.8–2.6 px | 0.7–2.0 px |
| Средняя ошибка уверенности точек | 0.69–0.93 | 0.003–0.012 |

## Предупреждения

- Калибровка выдала рекомендацию включить `zero_point` через `zp_cfg` для 50 матричных слоёв (`Consider enabling zero_point for these matrix layers via zp_cfg`). Не применялась.
- `NNPACK: Unsupported hardware` в контейнере под эмуляцией x86_64. На результат не влияет.
- Файл `yolov8n-pose_tail.onnx` весит 13 МБ: `get_sub_model` сохраняет все инициализаторы исходной модели.

## Загрузка и проверка на TPU

- Загрузка выполняется через интерфейс Jupyter: файл `ml/weights/yolov8n-pose_head_b1_o1_h1m.tpu` загрузить в рабочую папку и выполнить `! cp yolov8n-pose_head_b1_o1_h1m.tpu /auto/cache/<LOGIN>/`.
- Проверка `notebooks/linq_check.py --program yolov8n-pose_head_b1_o1_h1m.tpu --input data/videos/calib/0050.npy --input-name images`: не выполнена. Программа не загружена, в `.env` нет `LINQ_AMQP_*`, пакета `tpu_pycloud_format` нет вне Jupyter. Ожидаемые выходы — четыре тензора из таблицы «Результат».
