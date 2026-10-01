"""A small, closed JsonLogic evaluator for ``fixtures/architecture.jsonlogic.json``.

Only the operators the pack uses are supported; anything else raises, so a new
operator in the rules file is noticed instead of silently evaluating to null.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

RULES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "architecture.jsonlogic.json"

_MISSING = object()


def _var(path: str, data: Any) -> Any:
    cur = data
    for part in str(path).split(".") if path != "" else []:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def apply(rule: Any, data: Any) -> Any:
    """Evaluate *rule* against *data*."""
    if isinstance(rule, list):
        return [apply(r, data) for r in rule]
    if not isinstance(rule, dict):
        return rule
    if len(rule) != 1:
        raise ValueError(f"jsonlogic: a rule must have exactly one operator: {rule!r}")
    ((op, args),) = rule.items()
    if op == "var":
        path = args[0] if isinstance(args, list) else args
        return _var(path, data)
    if not isinstance(args, list):
        args = [args]
    if op == "if":
        for i in range(0, len(args) - 1, 2):
            if apply(args[i], data):
                return apply(args[i + 1], data)
        return apply(args[-1], data) if len(args) % 2 else None
    if op == "and":
        val: Any = True
        for a in args:
            val = apply(a, data)
            if not val:
                return val
        return val
    if op == "or":
        val = False
        for a in args:
            val = apply(a, data)
            if val:
                return val
        return val
    vals = [apply(a, data) for a in args]
    if op == "!":
        return not vals[0]
    if op == "!!":
        return bool(vals[0])
    if op == "==":
        return vals[0] == vals[1]
    if op in ("!=", "!=="):
        return vals[0] != vals[1]
    if op == "===":
        return vals[0] == vals[1] and type(vals[0]) is type(vals[1])
    if op == ">":
        return vals[0] is not None and vals[1] is not None and vals[0] > vals[1]
    if op == "in":
        return vals[1] is not None and vals[0] in vals[1]
    raise ValueError(f"jsonlogic: unsupported operator {op!r}")


@cache
def _rules_file(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rule(name: str, path: Path = RULES_PATH) -> Any:
    """A named rule from the pack's rules file (``rules.<name>`` or a top-level key)."""
    doc = _rules_file(str(path))
    if name in doc.get("rules", {}):
        return doc["rules"][name]
    if name in doc:
        return doc[name]
    raise KeyError(f"jsonlogic rule {name!r} not in {path.name}")
