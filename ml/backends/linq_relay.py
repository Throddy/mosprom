import json
import os
import time
import uuid

import cv2
import numpy as np
import pika

from core.schemas import Detection

MAX_SIDE = 640
JPEG_QUALITY = 90
TIMEOUT_S = 10
TIMING_KEYS = ("pre", "tpu", "post")

Scale = tuple[float, float]


class LinqRelayDetector:
    name = "yolov8n-pose+yolov8n tpu int8 via relay"

    def __init__(self) -> None:
        self._params = pika.ConnectionParameters(
            host=_env("LINQ_AMQP_HOST"), port=int(_env("LINQ_AMQP_PORT")),
            credentials=pika.PlainCredentials(_env("LINQ_AMQP_USER"), _env("LINQ_AMQP_PASSWORD")))
        self._request_queue = f"relay.{_env('LINQ_LOGIN')}.in"
        self._pending: set[str] = set()
        self._replies: dict[str, bytes] = {}
        self._connect()
        self.last_timing = {"pre": 0.0, "infer": 0.0, "post": 0.0}
        self.server_timing = {key: 0.0 for key in TIMING_KEYS}

    def infer(self, images: list[np.ndarray]) -> list[list[Detection]]:
        if not images:
            self.last_timing = {"pre": 0.0, "infer": 0.0, "post": 0.0}
            return []
        started = time.perf_counter()
        encoded = [_encode(image) for image in images]
        pre_done = time.perf_counter()
        bodies = self._request([jpeg for jpeg, _ in encoded])
        infer_done = time.perf_counter()
        replies = [_parse(body) for body in bodies]
        detections = [_to_detections(reply["detections"], scale)
                      for reply, (_, scale) in zip(replies, encoded)]
        self.server_timing = {key: sum(r["timing"][key] for r in replies) / len(replies)
                              for key in TIMING_KEYS}
        self.last_timing = {
            "pre": (pre_done - started) * 1000,
            "infer": (infer_done - pre_done) * 1000,
            "post": (time.perf_counter() - infer_done) * 1000,
        }
        return detections

    def _connect(self) -> None:
        try:
            self._connection = pika.BlockingConnection(self._params)
            self._channel = self._connection.channel()
            self._reply_queue = self._channel.queue_declare(queue="", exclusive=True).method.queue
            self._channel.basic_consume(queue=self._reply_queue, on_message_callback=self._on_reply,
                                        auto_ack=True)
        except pika.exceptions.AMQPError as error:
            raise RuntimeError(f"LinQ relay: нет подключения к брокеру ({type(error).__name__})") \
                from error

    def _request(self, jpegs: list[bytes]) -> list[bytes]:
        try:
            # Соединение могло закрыться брокером, пока детектор простаивал.
            self._connection.process_data_events(time_limit=0)
        except pika.exceptions.AMQPError:
            self._connect()
        ids = [uuid.uuid4().hex for _ in jpegs]
        self._pending, self._replies = set(ids), {}
        try:
            for request_id, jpeg in zip(ids, jpegs):
                self._channel.basic_publish(
                    exchange="", routing_key=self._request_queue, body=jpeg,
                    properties=pika.BasicProperties(reply_to=self._reply_queue,
                                                    correlation_id=request_id))
            self._wait()
        except pika.exceptions.AMQPError as error:
            raise RuntimeError(f"LinQ relay: ошибка обмена с брокером ({type(error).__name__})") \
                from error
        return [self._replies[request_id] for request_id in ids]

    def _wait(self) -> None:
        deadline = time.monotonic() + TIMEOUT_S
        received = 0
        while len(self._replies) < len(self._pending):
            self._connection.process_data_events(time_limit=0.01)
            if len(self._replies) > received:
                received, deadline = len(self._replies), time.monotonic() + TIMEOUT_S
            if time.monotonic() > deadline:
                raise RuntimeError(f"LinQ relay: нет ответа за {TIMEOUT_S} с, получено ответов "
                                   f"{received} из {len(self._pending)}")

    def _on_reply(self, channel, method, properties, body: bytes) -> None:
        if properties.correlation_id in self._pending:
            self._replies[properties.correlation_id] = body


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"нет переменной окружения {name}")
    return value


def _encode(image: np.ndarray) -> tuple[bytes, Scale]:
    h, w = image.shape[:2]
    factor = min(1.0, MAX_SIDE / max(h, w))
    new_w, new_h = round(w * factor), round(h * factor)
    small = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA) if factor < 1 else image
    ok, jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise RuntimeError("LinQ relay: не удалось закодировать кадр в JPEG")
    return jpeg.tobytes(), (new_w / w, new_h / h)


def _parse(body: bytes) -> dict:
    reply = json.loads(body)
    if "error" in reply:
        raise RuntimeError(f"LinQ relay: ошибка сервера: {reply['error']}")
    return reply


def _to_detections(items: list[dict], scale: Scale) -> list[Detection]:
    sx, sy = scale
    detections = []
    for item in items:
        x1, y1, x2, y2 = item["bbox"]
        kpts = None
        if item["kpts"] is not None:
            kpts = np.asarray(item["kpts"], dtype=np.float32) / np.array([sx, sy, 1], np.float32)
        detections.append(Detection(cls=item["cls"], conf=item["conf"],
                                    bbox=(x1 / sx, y1 / sy, x2 / sx, y2 / sy), kpts=kpts))
    return detections
