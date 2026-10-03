"""System Two sender (WP-50): a person's question explained in plain words, never decided.

A wired System Two role (``status: wired``, ``system: system_two``) of a synthetic tenant, in
``MODEL_CALLS=live`` with ``OPENROUTER_SYS2_API_KEY`` set, is sent to OpenRouter's chat
endpoint with its pinned model and provider: the card's brief (``model_roles.brief``) as the
system message and the question as JSON. The answer must be the card's output exactly
(:func:`check_explanation`): ``explanation`` (at most five sentences), ``facts_cited`` (each
``{field, value}`` found in the question) and ``missing``. Anything else, a non-200 or an
unreachable endpoint is recorded ``failed``; the question is shown without an explanation and
nothing waits on it. The explanation is shown next to the question; no node reads it.
"""

from __future__ import annotations

import json
import re
from typing import Any

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_S = 30.0
MAX_TOKENS = 2000
EXCERPT = 160  # of an answer that is not JSON, kept in the call's reason (synthetic only)
MAX_SENTENCES = 5
FIELDS = ("explanation", "facts_cited", "missing")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


class ExplainError(Exception):
    """The model's answer cannot be shown: the reason is recorded on the call."""


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        out = set(value)
        for v in value.values():
            out |= _keys(v)
        return out
    if isinstance(value, list):
        out: set[str] = set()
        for v in value:
            out |= _keys(v)
        return out
    return set()


def _scalars(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_scalars(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_scalars(v) for v in value)) if value else set()
    return {str(value)} if value is not None else set()


def check_explanation(question: dict[str, Any], content: str) -> dict[str, Any]:
    """The model's text as the card's output, or :class:`ExplainError` saying why not.

    A cited fact must come from the question: the last part of its ``field`` is a key there
    and its ``value`` is one of the question's values (a fact the model made up is refused).
    """
    if not isinstance(content, str) or not content.strip():
        raise ExplainError("the answer is empty")
    text = _FENCE.sub("", content.strip())
    start, end = text.find("{"), text.rfind("}")
    try:
        out = json.loads(text[start : end + 1] if 0 <= start < end else text)
    except json.JSONDecodeError:
        excerpt = " ".join(content.split())[:EXCERPT]
        raise ExplainError(f"the answer is not JSON: {excerpt!r}") from None
    if not isinstance(out, dict) or set(out) != set(FIELDS):
        got = sorted(out) if isinstance(out, dict) else type(out).__name__
        raise ExplainError(f"the answer must have exactly {list(FIELDS)}, not {got}")
    text = out["explanation"]
    if not isinstance(text, str) or not text.strip():
        raise ExplainError("explanation is empty")
    if len(_SENTENCE_END.findall(text.strip())) > MAX_SENTENCES:
        raise ExplainError(f"explanation is longer than {MAX_SENTENCES} sentences")
    missing = out["missing"]
    if not isinstance(missing, list) or not all(isinstance(m, str) for m in missing):
        raise ExplainError("missing must be a list of strings")
    facts = out["facts_cited"]
    if not isinstance(facts, list):
        raise ExplainError("facts_cited must be a list")
    keys, values = _keys(question), _scalars(question)
    for fact in facts:
        if not isinstance(fact, dict) or set(fact) != {"field", "value"}:
            raise ExplainError("each fact cited is {field, value}")
        name = re.split(r"[.\[\]]", str(fact["field"]).strip("[]. "))
        name = [p for p in name if p and not p.isdigit()]
        if not name or name[-1] not in keys:
            raise ExplainError(f"fact field {fact['field']!r} is not in the question")
        if str(fact["value"]) not in values:
            raise ExplainError(f"fact {fact['field']!r} = {fact['value']!r} is not in the question")
    return {"explanation": text.strip(), "facts_cited": facts, "missing": missing}


def request_body(role: Any, payload: dict[str, Any]) -> dict[str, Any]:
    from poarta_contabila.model_roles import brief

    return {
        "model": role.model,
        "messages": [
            {"role": "system", "content": brief(role)},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
        ],
        "provider": role.provider.model_dump(),
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "reasoning": {"enabled": False},  # WP-52: GLM spent the budget thinking, no answer
    }


def send(role: Any, payload: dict[str, Any], secret: str, http: Any = None) -> dict[str, Any]:
    """POST the question; the checked output plus who answered and the usage.

    :class:`ExplainError` on a non-200, an unreachable endpoint or an answer off the card.
    """
    import httpx

    client = http if http is not None else httpx.Client(timeout=TIMEOUT_S)
    try:
        try:
            resp = client.post(
                CHAT_URL,
                json=request_body(role, payload),
                headers={"Authorization": f"Bearer {secret}"},
            )
        except httpx.HTTPError as exc:
            raise ExplainError(f"OpenRouter unreachable: {type(exc).__name__}") from None
        if resp.status_code != 200:
            try:
                err = resp.json().get("error") or {}
            except ValueError:
                err = {}
            raise ExplainError(
                f"OpenRouter answered HTTP {resp.status_code} {err.get('code', '')}: "
                f"{str(err.get('message', ''))[:200]}".replace("  ", " ")
            )
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ExplainError("OpenRouter answered without a message") from None
        out = check_explanation(payload, content)
        usage = data.get("usage") or {}
        return {
            **out,
            "served_by": f"{data.get('model', role.model)} via {data.get('provider', '?')}",
            "usage": {
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "cost": usage.get("cost"),
            },
        }
    finally:
        if http is None:
            client.close()
