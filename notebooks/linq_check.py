import argparse
import json
import os
import time
import uuid
from pathlib import Path

import numpy as np
import pika
from PIL import Image
from tpu_pycloud_format import (MESSAGE_ID_ATTR_NAME, RESPONSE_ROUTING_KEYS_ATTR_NAME,
                                TARGET_URI_ATTR_NAME, PyTask, deserialize, serialize)

# Конвенции облака LinQ из example.ipynb.
EXCHANGE = "tpu.direct"
INPUT_QUEUE = "input"
PROGRAM_ROOT = "/auto/cache"
TIMEOUT_S = 60

DEFAULT_PROGRAM = "torch_resnet50_b1_o5_h1m.tpu"
DEFAULT_INPUT = ("~/linq/api/API/usage_example_python_api/usage_example_python_api/"
                 "ILSVRC2012_val_00000045.JPEG")
DEFAULT_INPUT_NAME = "input.1"
EXAMPLE_HW = (224, 224)
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"нет переменной окружения {name}")
    return value


def preprocess_example(image: Image.Image) -> np.ndarray:
    """Препроцессинг resnet50 из примера: центральный кроп 85 %, 224x224, NCHW float32."""
    image = image.convert("RGB")
    width, height = image.size
    side = int(min(width, height) * 0.85)
    left, top = (width - side) // 2, (height - side) // 2
    image = image.crop((left, top, left + side, top + side)).resize(EXAMPLE_HW)
    arr = (np.asarray(image) / 255.0 - IMAGENET_MEAN) / IMAGENET_STD
    return np.transpose(arr, (2, 0, 1))[np.newaxis].astype(np.float32)


def load_input(path: Path) -> np.ndarray:
    if path.suffix == ".npy":
        return np.load(path)
    with Image.open(path) as image:
        return preprocess_example(image)


def wait_reply(channel: pika.adapters.blocking_connection.BlockingChannel, queue: str,
               started: float) -> tuple[pika.BasicProperties, bytes]:
    for method, properties, body in channel.consume(queue, auto_ack=True,
                                                    inactivity_timeout=1.0):
        if method is not None:
            channel.cancel()
            return properties, body
        if time.monotonic() - started > TIMEOUT_S:
            raise TimeoutError(f"нет ответа за {TIMEOUT_S} с")
    raise RuntimeError("очередь ответов закрыта")


def call_tpu(tensors: dict[str, np.ndarray], program_path: str) -> tuple[dict, float]:
    credentials = pika.PlainCredentials(env("LINQ_AMQP_USER"), env("LINQ_AMQP_PASSWORD"))
    params = pika.ConnectionParameters(env("LINQ_AMQP_HOST"), int(env("LINQ_AMQP_PORT")),
                                       credentials=credentials)
    task_id = uuid.uuid4().hex
    reply_queue = f"notebook_{task_id[:8]}"
    connection = pika.BlockingConnection(params)
    try:
        channel = connection.channel()
        channel.queue_declare(queue=reply_queue, auto_delete=True)
        channel.queue_bind(exchange=EXCHANGE, queue=reply_queue, routing_key=reply_queue)
        started = time.monotonic()
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=INPUT_QUEUE,
            body=serialize(PyTask(tensors)),
            properties=pika.BasicProperties(headers={
                TARGET_URI_ATTR_NAME: f"file://{program_path}?raw=False",
                RESPONSE_ROUTING_KEYS_ATTR_NAME: json.dumps([reply_queue]),
                MESSAGE_ID_ATTR_NAME: task_id,
            }),
        )
        properties, body = wait_reply(channel, reply_queue, started)
        elapsed_ms = (time.monotonic() - started) * 1000
    finally:
        connection.close()
    if properties.headers[MESSAGE_ID_ATTR_NAME] != task_id:
        raise RuntimeError("ответ не на отправленную задачу")
    data, _, worker = deserialize(body)
    if not data:
        raise RuntimeError(f"ошибка воркера: {worker['error_message']}")
    return data, elapsed_ms


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", default=DEFAULT_PROGRAM)
    parser.add_argument("--input", type=Path, default=Path(DEFAULT_INPUT).expanduser())
    parser.add_argument("--input-name", default=DEFAULT_INPUT_NAME)
    args = parser.parse_args()

    program_path = f"{PROGRAM_ROOT}/{env('LINQ_LOGIN')}/{args.program}"
    tensors = {args.input_name: load_input(args.input)}
    outputs, elapsed_ms = call_tpu(tensors, program_path)
    for name, tensor in outputs.items():
        print(f"выход {name}: форма {tuple(tensor.shape)}")
    print(f"время запроса: {elapsed_ms:.0f} мс")


if __name__ == "__main__":
    main()
