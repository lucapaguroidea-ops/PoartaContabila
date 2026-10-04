"""System Two sender: a person's question explained in plain words, never decided.

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
from datetime import date
from typing import Any

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_S = 30.0
MAX_TOKENS = 6000  # reasoning counts against it
EXCERPT = 160  # of an answer that is not JSON, kept in the call's reason (synthetic only)
MAX_SENTENCES = 5
RETRIES = 1  # an answer off the card is asked once more, with the reason
RETRY_ASK = (
    "Your answer was refused: {reason}. Answer again with the JSON object only, following "
    "the Output rule: a non-empty explanation, and only single values from the input as facts."
)
FIELDS = ("explanation", "facts_cited", "missing")
EMPTY = ([], {}, "", None, "[]", "{}")
MIN_WORDS = 4  # an explanation of fewer words ("...", "N/A") explains nothing
# GLM refuses reasoning off; think little and keep it out of the answer. Other families
# get no reasoning field: Kimi answered empty with it.
REASONING = {"z-ai/": {"effort": "low", "exclude": True}}

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
_WORD = re.compile(r"[^\W\d_]{2,}")


class ExplainError(Exception):
    """The model's answer cannot be shown: the reason is recorded on the call."""


class PolicyRefused(ExplainError):
    """OpenRouter found no endpoint for the request's data policy (HTTP 404)."""


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
    if isinstance(out, dict) and len(out) == 1:  # {"answer": {...the card's fields...}}
        (inner,) = out.values()
        if isinstance(inner, str):  # Z.AI also sends the object as a JSON string
            try:
                inner = json.loads(_FENCE.sub("", inner.strip()))
            except json.JSONDecodeError:
                pass
        if isinstance(inner, dict) and set(inner) == set(FIELDS):
            out = inner
    if not isinstance(out, dict) or set(out) != set(FIELDS):
        got = sorted(out) if isinstance(out, dict) else type(out).__name__
        raise ExplainError(f"the answer must have exactly {list(FIELDS)}, not {got}")
    text = out["explanation"]
    if not isinstance(text, str) or not text.strip():
        raise ExplainError("explanation is empty")
    if len(_WORD.findall(text)) < MIN_WORDS:
        raise ExplainError(f"explanation is a placeholder, not words: {text.strip()[:40]!r}")
    if len(_SENTENCE_END.findall(text.strip())) > MAX_SENTENCES:
        raise ExplainError(f"explanation is longer than {MAX_SENTENCES} sentences")
    missing = out["missing"]
    if not isinstance(missing, list) or not all(isinstance(m, str) for m in missing):
        raise ExplainError("missing must be a list of strings")
    facts = out["facts_cited"]
    if not isinstance(facts, list):
        raise ExplainError("facts_cited must be a list")
    keys, values = _keys(question), _scalars(question)
    kept = []
    for fact in facts:
        if not isinstance(fact, dict) or set(fact) != {"field", "value"}:
            raise ExplainError("each fact cited is {field, value}")
        name = re.split(r"[.\[\]]", str(fact["field"]).strip("[]. "))
        name = [p for p in name if p and not p.isdigit()]
        if not name or name[-1] not in keys:
            raise ExplainError(f"fact field {fact['field']!r} is not in the question")
        if fact["value"] in EMPTY:  # an empty field claims nothing: dropped, not refused
            continue
        if str(fact["value"]) not in values:
            raise ExplainError(f"fact {fact['field']!r} = {fact['value']!r} is not in the question")
        kept.append(fact)
    return {"explanation": text.strip(), "facts_cited": kept, "missing": missing}


def request_body(
    role: Any, payload: dict[str, Any], provider: Any = None, as_of: str | None = None
) -> dict[str, Any]:
    from poarta_contabila.model_roles import brief

    # today's date goes with the question, not into the recorded input (its hash finds
    # the explanation again on later days)
    asked = {**payload, "as_of": as_of or date.today().isoformat()}
    body = {
        "model": role.model,
        "messages": [
            {"role": "system", "content": brief(role)},
            {"role": "user", "content": json.dumps(asked, ensure_ascii=False, sort_keys=True)},
        ],
        "provider": provider if provider is not None else role.provider.model_dump(),
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
    }
    for prefix, reasoning in REASONING.items():
        if role.model.startswith(prefix):
            body["reasoning"] = reasoning
    return body


def _sum(rows: list[dict[str, Any]], name: str) -> Any:
    values = [r.get(name) for r in rows if r.get(name) is not None]
    return sum(values) if values else None


def _post(client: Any, body: dict[str, Any], secret: str) -> tuple[dict[str, Any], Any]:
    """(the response JSON, the message content) or :class:`ExplainError`."""
    import httpx

    try:
        resp = client.post(CHAT_URL, json=body, headers={"Authorization": f"Bearer {secret}"})
    except httpx.HTTPError as exc:
        raise ExplainError(f"OpenRouter unreachable: {type(exc).__name__}") from None
    if resp.status_code != 200:
        try:
            err = resp.json().get("error") or {}
        except ValueError:
            err = {}
        msg = str(err.get("message", ""))[:200]
        reason = f"OpenRouter answered HTTP {resp.status_code} {err.get('code', '')}: {msg}"
        if resp.status_code == 404 and "data policy" in msg.lower():
            raise PolicyRefused(reason.replace("  ", " "))
        raise ExplainError(reason.replace("  ", " "))
    try:
        data = resp.json()
        message = data["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise ExplainError("OpenRouter answered without a message") from None
    content = message.get("content")
    if not (content or "").strip() and (message.get("reasoning") or "").strip():
        raise ExplainError("the answer is empty: the model wrote only reasoning")
    return data, content


def send(
    role: Any,
    payload: dict[str, Any],
    secret: str,
    http: Any = None,
    provider: Any = None,
    retries: int = RETRIES,
) -> dict[str, Any]:
    """POST the question; the checked output plus who answered and the usage.

    :class:`ExplainError` on a non-200, an unreachable endpoint or an answer off the card.
    """
    import httpx

    client = http if http is not None else httpx.Client(timeout=TIMEOUT_S)
    body = request_body(role, payload, provider)
    spent: list[dict[str, Any]] = []
    try:
        for attempt in range(1 + retries):
            data, content = _post(client, body, secret)
            spent.append(data.get("usage") or {})
            try:
                out = check_explanation(payload, content)
            except ExplainError as exc:
                if attempt == retries:
                    raise ExplainError(f"{exc} (after {attempt + 1} answers)") from None
                body = {
                    **body,
                    "messages": [
                        *body["messages"],
                        {"role": "assistant", "content": content or ""},
                        {"role": "user", "content": RETRY_ASK.format(reason=exc)},
                    ],
                }
                continue
            return {
                **out,
                "served_by": f"{data.get('model', role.model)} via {data.get('provider', '?')}",
                "answers": attempt + 1,
                "usage": {
                    "input_tokens": _sum(spent, "prompt_tokens"),
                    "output_tokens": _sum(spent, "completion_tokens"),
                    "cost": _sum(spent, "cost"),
                },
            }
        raise AssertionError("unreachable")
    finally:
        if http is None:
            client.close()
