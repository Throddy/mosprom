import json
import os

import cv2
import numpy as np
import pika
import yaml

from core.schemas import Detection
from ml import ROOT
from ml.backends.linq import LinqDetector

REPORT_EVERY = 100
TIMING_KEYS = ("pre", "tpu", "post")


def main() -> None:
    models_cfg = yaml.safe_load((ROOT / "configs/models.yaml").read_text())["models"]
    detector = LinqDetector(models_cfg, ROOT)
    connection = pika.BlockingConnection(pika.ConnectionParameters(
        host=_env("LINQ_AMQP_HOST"), port=int(_env("LINQ_AMQP_PORT")),
        credentials=pika.PlainCredentials(_env("LINQ_AMQP_USER"), _env("LINQ_AMQP_PASSWORD"))))
    channel = connection.channel()
    queue = f"relay.{_env('LINQ_LOGIN')}.in"
    channel.queue_declare(queue=queue, durable=False)
    channel.basic_qos(prefetch_count=1)
    timings: list[dict[str, float]] = []

    def on_message(ch, method, properties, body: bytes) -> None:
        reply = handle(detector, body)
        ch.basic_publish(exchange="", routing_key=properties.reply_to,
                         body=json.dumps(reply).encode(),
                         properties=pika.BasicProperties(correlation_id=properties.correlation_id,
                                                         content_type="application/json"))
        ch.basic_ack(delivery_tag=method.delivery_tag)
        if "timing" in reply:
            timings.append(reply["timing"])
        if len(timings) == REPORT_EVERY:
            means = {key: sum(t[key] for t in timings) / len(timings) for key in TIMING_KEYS}
            summary = ", ".join(f"{key} {value:.1f} мс" for key, value in means.items())
            print(f"кадров {len(timings)}: {summary}", flush=True)
            timings.clear()

    channel.basic_consume(queue=queue, on_message_callback=on_message)
    print(f"relay: очередь {queue}, детектор {detector.name}", flush=True)
    channel.start_consuming()


def handle(detector: LinqDetector, body: bytes) -> dict:
    """Ответ по протоколу ретранслятора: детекции и timing в мс или {"error": текст}."""
    frame = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return {"error": "не удалось декодировать JPEG"}
    try:
        detections = detector.infer([frame])[0]
    except (RuntimeError, cv2.error) as error:
        return {"error": str(error)}
    timing = detector.last_timing
    return {
        "detections": [_to_json(det) for det in detections],
        "timing": {"pre": timing["pre"], "tpu": timing["infer"], "post": timing["post"]},
    }


def _to_json(det: Detection) -> dict:
    return {
        "cls": det.cls,
        "conf": det.conf,
        "bbox": list(det.bbox),
        "kpts": det.kpts.tolist() if det.kpts is not None else None,
    }


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"нет переменной окружения {name}")
    return value


if __name__ == "__main__":
    main()
