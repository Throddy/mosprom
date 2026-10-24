"""Реестр правил: каждый модуль пакета logic.rules даёт подклассы Rule."""
import importlib
import inspect
import logging
import pkgutil

from logic.rules.base import Rule

log = logging.getLogger(__name__)

RULES: dict[str, Rule] = {}


def register(rule: Rule) -> None:
    RULES[rule.type] = rule


def describe() -> list[dict]:
    return [
        {"type": r.type, "title": r.title, "severity": r.severity, "needs_zone": r.needs_zone,
         "params": r.params}
        for r in RULES.values()
    ]


def _discover() -> None:
    for info in pkgutil.iter_modules(__path__):
        if info.name == "base" or info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{__name__}.{info.name}")
        except Exception:
            log.exception("правило %s не загружено", info.name)
            continue
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, Rule) and cls is not Rule and cls.__module__ == module.__name__ \
                    and getattr(cls, "type", None):
                register(cls())


_discover()
