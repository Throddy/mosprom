from logic.engine import Engine, Result
from logic.rules import RULES, describe, register

# Имя из комментария в core/schemas.py
rule_specs = describe

__all__ = ["Engine", "Result", "RULES", "describe", "register", "rule_specs"]
