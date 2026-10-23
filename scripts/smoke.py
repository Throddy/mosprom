"""Smoke-тест. Сейчас проверяет импорт модулей контракта. Полная версия: задача BE-5."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.config  # noqa: E402
import core.schemas  # noqa: E402
import logic  # noqa: E402
import ml  # noqa: E402

print("smoke: ok")
