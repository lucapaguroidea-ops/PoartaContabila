"""Typed human-in-the-loop questions (ARCHITECTURE §8).

``ask`` wraps ``langgraph.types.interrupt``: the resume body must validate
against a closed model (``extra=forbid``) and an optional check. An invalid
answer does not raise out of the node (that would leave the bad answer stored
on the thread and replayed on every resume); it re-asks with the error, so the
next resume is judged afresh. Place ``ask`` before any side effect: the node
re-runs from its first line on every resume.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from langgraph.types import interrupt
from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)


def ask(
    kind: str,
    payload: dict[str, Any],
    model: type[M],
    check: Callable[[M], str | None] | None = None,
) -> M:
    """Pause the graph with an interrupt of *kind*; return the validated answer."""
    question = {"kind": kind, **payload}
    while True:
        raw = interrupt(question)
        try:
            answer = model.model_validate(raw)
        except ValidationError as exc:
            question = {"kind": kind, **payload, "error": exc.errors(include_url=False)}
            continue
        problem = check(answer) if check else None
        if problem is None:
            return answer
        question = {"kind": kind, **payload, "error": problem}
