import ast
import json
import os
import time
import uuid
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pika
from pika.adapters.blocking_connection import BlockingChannel
from tpu_pycloud_format import (MESSAGE_ID_ATTR_NAME, RESPONSE_ROUTING_KEYS_ATTR_NAME,
                                TARGET_URI_ATTR_NAME, PyTask, deserialize, serialize)

from core.schemas import Detection
from ml.prepost import IOU, postprocess_det, postprocess_pose, preprocess

# Конвенции облака LinQ: notebooks/linq.md, раздел «Вызов через API».
EXCHANGE = "tpu.direct"
INPUT_QUEUE = "input"
PROGRAM_ROOT = "/auto/cache"
INPUT_NAME = "images"
TIMEOUT_S = 60

Task = tuple[str, np.ndarray]


class LinqDetector:
    name = "yolov8n-pose tpu int8 + yolov8n tpu int8"

    def __init__(self, models_cfg: dict, root: Path) -> None:
        pose_cfg, det_cfg, linq_cfg = models_cfg["pose"], models_cfg["det"], models_cfg["linq"]
        program_dir = f"{PROGRAM_ROOT}/{_env('LINQ_LOGIN')}"
        self._pose_uri = f"file://{program_dir}/{linq_cfg['pose_program']}?raw=False"
        self._det_uri = f"file://{program_dir}/{linq_cfg['det_program']}?raw=False"
        self._pose_tail = ort.InferenceSession(str(_tail_path(root / pose_cfg["weights"])))
        self._det_tail = ort.InferenceSession(str(_tail_path(root / det_cfg["weights"])))
        det_meta = ort.InferenceSession(str(root / det_cfg["weights"])).get_modelmeta()
        self._class_names = ast.literal_eval(det_meta.custom_metadata_map["names"])
        self._pose_conf, self._det_conf = pose_cfg["conf"], det_cfg["conf"]
        self._det_keep = set(det_cfg["classes"])
        self._params = pika.ConnectionParameters(
            host=_env("LINQ_AMQP_HOST"), port=int(_env("LINQ_AMQP_PORT")),
            credentials=pika.PlainCredentials(_env("LINQ_AMQP_USER"), _env("LINQ_AMQP_PASSWORD")))
        self.last_timing = {"pre": 0.0, "infer": 0.0, "post": 0.0}

    def infer(self, images: list[np.ndarray]) -> list[list[Detection]]:
        if not images:
            self.last_timing = {"pre": 0.0, "infer": 0.0, "post": 0.0}
            return []
        started = time.perf_counter()
        prepared = [preprocess(image) for image in images]
        pre_done = time.perf_counter()
        tasks = [task for tensor, _ in prepared
                 for task in ((self._pose_uri, tensor), (self._det_uri, tensor))]
        outputs = self._call(tasks)
        infer_done = time.perf_counter()
        detections = [
            self._decode(outputs[2 * i], outputs[2 * i + 1], meta, (image.shape[1], image.shape[0]))
            for i, (image, (_, meta)) in enumerate(zip(images, prepared))
        ]
        self.last_timing = {
            "pre": (pre_done - started) * 1000,
            "infer": (infer_done - pre_done) * 1000,
            "post": (time.perf_counter() - infer_done) * 1000,
        }
        return detections

    def _decode(self, pose_out: dict, det_out: dict, meta: tuple[float, int, int],
                frame_size: tuple[int, int]) -> list[Detection]:
        pose = _run_tail(self._pose_tail, pose_out)
        det = _run_tail(self._det_tail, det_out)
        return (postprocess_pose(pose, meta, frame_size, self._pose_conf, IOU)
                + postprocess_det(det, meta, frame_size, self._det_conf, IOU,
                                  self._class_names, self._det_keep))

    def _call(self, tasks: list[Task]) -> list[dict[str, np.ndarray]]:
        try:
            connection = pika.BlockingConnection(self._params)
        except pika.exceptions.AMQPError as error:
            raise RuntimeError(f"LinQ: нет подключения к брокеру ({type(error).__name__})") \
                from error
        try:
            channel = connection.channel()
            reply_queue = f"linq_{uuid.uuid4().hex[:8]}"
            channel.queue_declare(queue=reply_queue, auto_delete=True)
            channel.queue_bind(exchange=EXCHANGE, queue=reply_queue, routing_key=reply_queue)
            task_ids = [_publish(channel, reply_queue, uri, tensor) for uri, tensor in tasks]
            replies = _collect(channel, reply_queue, set(task_ids))
        except pika.exceptions.AMQPError as error:
            raise RuntimeError(f"LinQ: ошибка обмена с брокером ({type(error).__name__})") \
                from error
        finally:
            if connection.is_open:
                connection.close()
        return [_unpack(replies[task_id]) for task_id in task_ids]


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"нет переменной окружения {name}")
    return value


def _tail_path(weights: Path) -> Path:
    # Часть графа после узлов разреза выполняется на CPU: notebooks/compile.md.
    return weights.with_name(f"{weights.stem}_tail.onnx")


def _run_tail(session: ort.InferenceSession, outputs: dict[str, np.ndarray]) -> np.ndarray:
    feed = {i.name: outputs[i.name] for i in session.get_inputs()}
    return session.run(["output0"], feed)[0]


def _publish(channel: BlockingChannel, reply_queue: str, uri: str, tensor: np.ndarray) -> str:
    task_id = uuid.uuid4().hex
    channel.basic_publish(
        exchange=EXCHANGE,
        routing_key=INPUT_QUEUE,
        body=serialize(PyTask({INPUT_NAME: tensor})),
        properties=pika.BasicProperties(headers={
            TARGET_URI_ATTR_NAME: uri,
            RESPONSE_ROUTING_KEYS_ATTR_NAME: json.dumps([reply_queue]),
            MESSAGE_ID_ATTR_NAME: task_id,
        }),
    )
    return task_id


def _collect(channel: BlockingChannel, reply_queue: str, task_ids: set[str]) -> dict[str, bytes]:
    replies: dict[str, bytes] = {}
    deadline = time.monotonic() + TIMEOUT_S
    for method, properties, body in channel.consume(reply_queue, auto_ack=True,
                                                    inactivity_timeout=1.0):
        task_id = (properties.headers or {}).get(MESSAGE_ID_ATTR_NAME) if method else None
        if task_id in task_ids:
            replies[task_id] = body
            deadline = time.monotonic() + TIMEOUT_S
        if len(replies) == len(task_ids):
            channel.cancel()
            return replies
        if time.monotonic() > deadline:
            raise RuntimeError(f"LinQ: нет ответа за {TIMEOUT_S} с, получено ответов "
                               f"{len(replies)} из {len(task_ids)}")
    raise RuntimeError("LinQ: очередь ответов закрыта брокером")


def _unpack(body: bytes) -> dict[str, np.ndarray]:
    data, _, worker = deserialize(body)
    if not data:
        raise RuntimeError(f"LinQ: ошибка воркера: {worker['error_message']}")
    return data
