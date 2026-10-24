"""Проверка камеры из PUT /api/cameras/{id}."""
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MAX_NAME = 100
MAX_POINTS = 50
MAX_ZONES = 20
MAX_RULES = 20
MAX_PARAM = 1000.0


def sanitize(text) -> str:
    """Значение из запроса для лога: без переводов строк, не длиннее 200 символов."""
    return str(text).replace("\r", " ").replace("\n", " ")[:200]


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _nonempty(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _check_source(source, errors: list[str]) -> None:
    if not isinstance(source, str) or not source:
        errors.append("source: нужна строка")
        return
    if source.startswith("rtsp://"):
        return
    path = Path(source)
    if path.is_absolute() or ".." in path.parts or not source.startswith("data/"):
        errors.append("source: нужен rtsp:// или относительный путь внутри data/ без ..")
        return
    if not (ROOT / path).exists():
        errors.append(f"source: {sanitize(source)} не найден")


def _check_zones(zones, errors: list[str]) -> set[str]:
    ids: set[str] = set()
    if not isinstance(zones, list):
        errors.append("zones: нужен список")
        return ids
    if len(zones) > MAX_ZONES:
        errors.append(f"zones: не больше {MAX_ZONES} зон")
        return ids
    for i, z in enumerate(zones):
        if not isinstance(z, dict):
            errors.append(f"zones[{i}]: нужен объект")
            continue
        zid = z.get("id")
        if not isinstance(zid, str):
            errors.append(f"zones[{i}].id: должен быть строкой")
        elif not _nonempty(zid):
            errors.append(f"zones[{i}].id: нужна непустая строка")
        elif zid in ids:
            errors.append(f"zones[{i}].id: {sanitize(zid)} повторяется")
        else:
            ids.add(zid)
        name = z.get("name")
        if not isinstance(name, str):
            errors.append(f"zones[{i}].name: должен быть строкой")
        elif len(name) > MAX_NAME:
            errors.append(f"zones[{i}].name: строка до {MAX_NAME} символов")
        polygon = z.get("polygon")
        if not isinstance(polygon, list) or not 3 <= len(polygon) <= MAX_POINTS:
            errors.append(f"zones[{i}].polygon: от 3 до {MAX_POINTS} точек")
            continue
        for p in polygon:
            if not isinstance(p, (list, tuple)) or len(p) != 2 or not all(_number(v) and 0 <= v <= 1 for v in p):
                errors.append(f"zones[{i}].polygon: координаты — числа от 0 до 1")
                break
    return ids


def _check_rule(i: int, rule, zone_ids: set[str], specs: dict[str, dict], errors: list[str]) -> None:
    if not isinstance(rule, dict):
        errors.append(f"rules[{i}]: нужен объект")
        return
    # Тип проверяется до поиска в словарях: список или объект как ключ дал бы исключение и 500
    rule_type = rule.get("type")
    if not isinstance(rule_type, str):
        errors.append(f"rules[{i}].type: должен быть строкой")
        return
    spec = specs.get(rule_type)
    if spec is None:
        errors.append(f"rules[{i}].type: неизвестное правило {sanitize(rule_type)}")
        return
    zone = rule.get("zone")
    if zone is not None and not isinstance(zone, str):
        errors.append(f"rules[{i}].zone: должен быть строкой")
    elif spec.get("needs_zone") and zone is None:
        errors.append(f"rules[{i}].zone: правилу {spec['type']} нужна зона")
    elif zone is not None and zone not in zone_ids:
        errors.append(f"rules[{i}].zone: зоны {sanitize(zone)} нет у камеры")
    schedule = rule.get("schedule")
    if schedule is not None:
        if not isinstance(schedule, (list, tuple)) or len(schedule) != 2 \
                or not all(isinstance(t, str) and TIME_RE.match(t) for t in schedule):
            errors.append(f"rules[{i}].schedule: null или две строки HH:MM")
    params = rule.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        errors.append(f"rules[{i}].params: должен быть объектом")
        return
    known = {p["name"] for p in spec.get("params", [])}
    for name, value in params.items():
        if name not in known:
            errors.append(f"rules[{i}].params: неизвестный параметр {sanitize(name)}")
        elif not _number(value) or not 0 <= value <= MAX_PARAM:
            errors.append(f"rules[{i}].params.{name}: число от 0 до {MAX_PARAM:g}")


def validate_camera(cam: dict, rules: dict[str, dict]) -> list[str]:
    """Ошибки камеры на русском, пустой список при успехе. rules — описания правил по type."""
    errors: list[str] = []
    if not isinstance(cam, dict):
        return ["нужен объект камеры"]
    if not _nonempty(cam.get("id")):
        errors.append("id: нужна непустая строка")
    name = cam.get("name")
    if not _nonempty(name) or len(name) > MAX_NAME:
        errors.append(f"name: непустая строка до {MAX_NAME} символов")
    fps = cam.get("fps")
    if not _number(fps) or not 0 < fps <= 30:
        errors.append("fps: число, 0 < fps <= 30")
    _check_source(cam.get("source"), errors)
    zone_ids = _check_zones(cam.get("zones", []), errors)
    rule_list = cam.get("rules", [])
    if not isinstance(rule_list, list):
        errors.append("rules: нужен список")
    elif len(rule_list) > MAX_RULES:
        errors.append(f"rules: не больше {MAX_RULES} правил")
    else:
        for i, rule in enumerate(rule_list):
            _check_rule(i, rule, zone_ids, rules, errors)
    return errors
