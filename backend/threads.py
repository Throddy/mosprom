"""Ограничение потоков ONNX Runtime, PyTorch и OpenCV до создания детекторов.

По умолчанию каждая сессия ONNX Runtime берёт столько потоков, сколько ядер. На сервере с 32 ядрами
четыре сессии (pose и det обычного детектора и детектора с плитками) и потоки PyTorch вытесняют друг друга.
Детектор создаёт ultralytics (ml/, зона ML) вызовом onnxruntime.InferenceSession(weight, session_options, ...),
поэтому класс подменяется в модуле onnxruntime до создания детекторов.

ORT_THREADS, TORCH_THREADS, CV2_THREADS: 0 — не ограничивать. Подменённые torch.set_num_threads и cv2.setNumThreads
всегда ставят заданное значение: ultralytics сам вызывает их при импорте и настройке предсказателя.
На macOS OpenCV собран с GCD, там cv2.setNumThreads не действует.
"""
import logging
import os
import threading

log = logging.getLogger(__name__)

_lock = threading.Lock()
_done = False
_ort = {"threads": 0}  # потоков на сессию ONNX Runtime для новых сессий; 0 — по умолчанию ORT


def _env_int(name: str) -> int:
    return max(0, int(os.environ.get(name, "0") or 0))


def set_ort_threads(threads: int) -> None:
    """Потоков на сессию для сессий, созданных после вызова. Используется limit_threads() и bench_cameras.py."""
    import onnxruntime as ort

    _ort["threads"] = threads
    if getattr(ort.InferenceSession, "_mosprom_limited", False):
        return
    base = ort.InferenceSession

    class LimitedSession(base):
        _mosprom_limited = True

        def __init__(self, path_or_bytes, sess_options=None, *args, **kwargs):
            n = _ort["threads"]
            if n > 0:
                sess_options = sess_options if sess_options is not None else ort.SessionOptions()
                sess_options.intra_op_num_threads = n
                sess_options.inter_op_num_threads = 1
                sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            super().__init__(path_or_bytes, sess_options, *args, **kwargs)

    ort.InferenceSession = LimitedSession


def limit_threads() -> None:
    """Один раз за процесс: ORT_THREADS, TORCH_THREADS, CV2_THREADS из окружения."""
    global _done
    with _lock:
        if _done:
            return
        _done = True
        ort_threads, torch_threads, cv2_threads = (_env_int(n) for n in ("ORT_THREADS", "TORCH_THREADS", "CV2_THREADS"))
        if ort_threads:
            set_ort_threads(ort_threads)
        if torch_threads:
            import torch

            # ultralytics в select_device при каждой настройке предсказателя вызывает torch.set_num_threads:
            # подменённая функция всегда ставит TORCH_THREADS
            set_torch = torch.set_num_threads
            set_torch(torch_threads)
            torch.set_num_threads = lambda n: set_torch(torch_threads)
            try:
                torch.set_num_interop_threads(1)
            except RuntimeError:
                # interop задаётся только до первой параллельной работы torch
                log.warning("TORCH_THREADS: число interop-потоков torch уже задано")
        if cv2_threads:
            import cv2

            # ultralytics при импорте вызывает cv2.setNumThreads(0): подменённая функция всегда ставит CV2_THREADS
            set_cv2 = cv2.setNumThreads
            set_cv2(cv2_threads)
            cv2.setNumThreads = lambda n: set_cv2(cv2_threads)
        log.info("потоки: ORT_THREADS=%s TORCH_THREADS=%s CV2_THREADS=%s, ядер %s",
                 ort_threads or "по умолчанию", torch_threads or "по умолчанию", cv2_threads or "по умолчанию",
                 os.cpu_count())
