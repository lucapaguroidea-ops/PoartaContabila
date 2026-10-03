"""Jev, System One inside nodes (ARCHITECTURE §12): ``v3_judge`` and ``v2_declaration_gate``.

- **JSON only.** An answer is a JSON object that validates against the pack's closed model
  (unknown keys refused, values not coerced). Anything else is no answer.
- **Cache on ``(pack, input_hash)``.** The hash covers the pack name, its version and the
  input, so a question is paid for once and a changed pack never reuses an old answer.
  Only validated answers are cached.
- **Fail closed.** No transport, a transport error, a timeout or an invalid answer raise
  :class:`JevError`. Layer 1 (:func:`make_judge`) then returns a verdict that asks a person;
  Layer 2 (:func:`make_v2`) gives no suggestion. Jev never opens a gate by itself.
- **Layer 2 cannot clear ``material``**: ``close.py`` drops such suggestions.

The wire (WP-20, RESEARCH_LOG.md R2): OpenRouter's Decisions endpoint (``POST
/api/alpha/decisions``, bearer ``OPENROUTER_SYS2_API_KEY``: one OpenRouter key for both
systems, WP-49) with the role's pinned model and provider, ``state`` = the pack input and
``questions`` = the role card's questions. Each
answer (``noul`` probability; ``choice`` + ``confidence``) is mapped onto the pack's closed
model by the card's thresholds; below them a field takes its cautious value (``CAUTIOUS``).
Only for a synthetic tenant (``route_check``), only in ``MODEL_CALLS=live``, only for the
wired packs. The direct TypeSafe route (:func:`http_transport`) is not built and refuses.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from poarta_contabila.types import CanonicalDocument, Closed, PeriodDiff


class V3Judge(Closed):
    """Layer 1 (``v3_judge``): may the job package without a person?"""

    accounts_ok: bool
    risk: Literal["low", "medium", "high"]
    needs_human: bool


class V2Gate(Closed):
    """Layer 2 (``v2_declaration_gate``): a suggestion to the person closing the month."""

    books_support_declaration: bool
    gap_materiality: Literal["none", "immaterial", "material"]
    action: Literal["file", "hold", "patch_maps", "reopen"]


class ReconReview(Closed):
    """``recon_review`` (``reconcile_sink.llm_review``, JevAnnex ``jev_recon_review``)."""

    verdict: Literal["confirm", "contest", "abstain"]


PACKS: dict[str, tuple[str, type[Closed]]] = {
    "v3_judge": ("1", V3Judge),
    "v2_declaration_gate": ("1", V2Gate),
    "recon_review": ("1", ReconReview),
}
"""pack → (version, closed output model). A new version never reuses cached answers."""

Transport = Callable[[str, dict[str, Any], float], Any]
"""(pack, input, timeout_s) → the answer as JSON text or a decoded object."""


class JevError(RuntimeError):
    """No usable answer: callers fail closed."""


class JevNotDocumented(JevError):
    """The wire has not been read from the official docs; nothing is sent."""


def input_hash(pack: str, payload: dict[str, Any], pin: dict[str, str] | None = None) -> str:
    """Cache key: pack, its version, the input and (when given) the role's model + card hash."""
    version = PACKS[pack][0]
    key: dict[str, Any] = {"pack": pack, "version": version, "input": payload}
    if pin:
        key["pin"] = pin
    body = json.dumps(
        key,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(body.encode()).hexdigest()


def validate(pack: str, raw: Any) -> Closed:
    """*raw* as the pack's closed model, or :class:`JevError`."""
    model = PACKS[pack][1]
    try:
        if isinstance(raw, str | bytes | bytearray):
            return model.model_validate_json(raw)
        if isinstance(raw, dict):
            return model.model_validate(raw)
    except ValidationError as exc:
        raise JevError(
            f"{pack}: answer is not {model.__name__} JSON ({exc.error_count()} error(s))"
        ) from exc
    raise JevError(f"{pack}: answer is not a JSON object")


# ----- cache -----


@dataclass
class InMemoryJevCache:
    rows: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def get(self, pack: str, key: str) -> dict[str, Any] | None:
        return self.rows.get((pack, key))

    def put(self, pack: str, key: str, body: dict[str, Any]) -> None:
        self.rows.setdefault((pack, key), body)


class PostgresJevCache:
    """``domain.jev_answers``, one row per ``(pack, input_hash)``."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def get(self, pack: str, key: str) -> dict[str, Any] | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT body FROM domain.jev_answers WHERE pack = %s AND input_hash = %s",
                (pack, key),
            ).fetchone()
        return row[0] if row else None

    def put(self, pack: str, key: str, body: dict[str, Any]) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.jev_answers (pack, input_hash, body) VALUES (%s, %s, %s)"
                " ON CONFLICT (pack, input_hash) DO NOTHING",
                (pack, key, json.dumps(body)),
            )


# ----- client -----


@dataclass(frozen=True)
class JevAnswer:
    pack: str
    input_hash: str
    body: Closed
    cached: bool


@dataclass
class Jev:
    transport: Transport
    cache: Any = field(default_factory=InMemoryJevCache)  # InMemoryJevCache | PostgresJevCache
    timeout_s: float = 20.0
    pin: Callable[[str], dict[str, str]] | None = None
    """pack → {model, card}: a changed model or role card never reuses a cached answer."""

    def ask(self, pack: str, payload: dict[str, Any]) -> JevAnswer:
        """The validated answer, from the cache or the transport; :class:`JevError` otherwise."""
        if pack not in PACKS:
            raise JevError(f"unknown Jev pack {pack!r}")
        try:
            key = input_hash(pack, payload, self.pin(pack) if self.pin else None)
            hit = self.cache.get(pack, key)
        except Exception as exc:
            raise JevError(f"{pack}: cache unavailable: {type(exc).__name__}") from exc
        if hit is not None:
            try:
                return JevAnswer(pack, key, validate(pack, hit), cached=True)
            except JevError:
                pass  # a row the closed model no longer accepts is no answer: ask again
        try:
            raw = self.transport(pack, payload, self.timeout_s)
        except JevError:
            raise
        except Exception as exc:  # timeout, connection, HTTP status
            raise JevError(f"{pack}: {type(exc).__name__}: {exc}") from exc
        body = validate(pack, raw)
        try:
            self.cache.put(pack, key, body.model_dump(mode="json"))
        except Exception as exc:
            raise JevError(f"{pack}: cache unavailable: {type(exc).__name__}") from exc
        return JevAnswer(pack, key, body, cached=False)


def http_transport(base_url: str, api_key: str) -> Transport:
    """The Jev HTTP call. Refuses until the wire is quoted from the official docs."""

    def call(pack: str, payload: dict[str, Any], timeout_s: float) -> Any:
        raise JevNotDocumented(
            f"{pack}: the Jev wire format has not been read from the official docs "
            "(RESEARCH_LOG.md); nothing was sent"
        )

    return call


DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
CAUTIOUS: dict[tuple[str, str], str] = {
    ("v3_judge", "risk"): "high",
    ("v2_declaration_gate", "gap_materiality"): "material",
    ("v2_declaration_gate", "action"): "hold",
    ("recon_review", "verdict"): "abstain",  # what no answer means: the det verdict stands
}
"""(pack, field) → the value a ``choice`` takes below the card's confidence threshold."""
_CAUTIOUS_NOUL = {"needs_human": True}  # every other noul is false unless clearly yes


def decision_questions(role: Any) -> dict[str, Any]:
    """The role card's questions as the Decisions API takes them; :class:`JevError` for a
    question whose criteria are not written in the card (``criteria_from``)."""
    out = {}
    for name, q in (role.card.get("questions") or {}).items():
        if q.get("criteria_from"):
            raise JevError(f"{role.role_id}: {name} takes its criteria from {q['criteria_from']}")
        out[name] = {k: q[k] for k in ("type", "instructions", "criteria") if k in q}
    return out


def map_answers(role: Any, pack: str, answers: Any) -> dict[str, Any]:
    """The Decisions answers as the pack's fields, by the card's thresholds (fail closed)."""
    if not isinstance(answers, dict):
        raise JevError(f"{role.role_id}: the answer has no answers object")
    card = role.card
    thresholds = card.get("thresholds") or {}
    questions = card.get("questions") or {}
    out: dict[str, Any] = {}
    fell_back = []
    for field_name, source in (card.get("fields") or {}).items():
        qname, _, attr = str(source).partition(".")
        q, a = questions.get(qname) or {}, answers.get(qname)
        if not isinstance(a, dict) or a.get("type") != q.get("type") or attr:
            raise JevError(f"{role.role_id}: no {q.get('type')} answer for {qname}")
        try:
            if q["type"] == "noul":
                p = float(a["noul"])
                if not 0 <= p <= 1:
                    raise ValueError(p)
                if _CAUTIOUS_NOUL.get(field_name):  # asks a person from a small chance
                    out[field_name] = p >= float(thresholds["human"])
                else:
                    out[field_name] = p >= float(thresholds["noul_yes"])
            elif q["type"] == "choice":
                choice, confidence = a["choice"], float(a["confidence"])
                if choice not in (q.get("criteria") or {}) or not 0 <= confidence <= 1:
                    raise ValueError(choice)
                if confidence >= float(thresholds["choice"]):
                    out[field_name] = choice
                else:
                    out[field_name] = CAUTIOUS[(pack, field_name)]
                    fell_back.append(field_name)
            else:
                raise JevError(f"{role.role_id}: {q['type']} answers are not mapped")
        except (KeyError, TypeError, ValueError) as exc:
            raise JevError(f"{role.role_id}: {qname}: answer off the card ({exc!r})") from None
    if pack == "v3_judge" and fell_back:
        out["needs_human"] = True  # an unsure risk is a person's to judge
    return out


def payload_cui(payload: dict[str, Any]) -> str | None:
    """The tenant a pack input belongs to (for the synthetic-only rule)."""
    if isinstance(payload.get("tenant_cui"), str):
        return payload["tenant_cui"]
    diff = payload.get("diff")
    return diff.get("cui") if isinstance(diff, dict) else None


def role_pin(roles: dict[str, Any]) -> Callable[[str], dict[str, str]]:
    """``Jev.pin`` from the model-role catalog: the pack's role model and card hash."""
    from poarta_contabila.model_roles import RouteRefused, role_for_pack

    def pin(pack: str) -> dict[str, str]:
        try:
            role = role_for_pack(roles, pack)
        except RouteRefused:
            return {}
        return {"role": role.role_id, "model": role.model or "", "card": role.card_hash}

    return pin


def role_transport(
    roles: dict[str, Any],
    *,
    mode: str,
    calls: Any,
    synthetic: Callable[[str | None], bool],
    http: Any = None,
    key: Callable[[str], str | None] = os.environ.get,
) -> Transport:
    """The transport behind the model-role catalog (``model_roles``).

    ``off``: refuses. ``dry``: the role and the tenant are checked (``route_check``) and the
    call is recorded in *calls* (``domain.model_calls``) with exactly what the role would be
    sent; then :class:`JevError`, so the node fails closed as if Jev gave no answer.
    ``live`` (WP-20): a wired role of a synthetic tenant is sent to OpenRouter's Decisions
    endpoint when its key is set, and recorded ``sent`` (or ``failed``); without the key it
    records as in ``dry``. *http*: an ``httpx.Client`` (tests); *key*: the env lookup.
    """
    from poarta_contabila.model_roles import RouteRefused, record, role_for_pack, route_check

    def call(pack: str, payload: dict[str, Any], timeout_s: float) -> Any:
        if mode not in ("dry", "live"):
            raise JevError(f"{pack}: model calls are {mode!r}")
        try:
            role = role_for_pack(roles, pack)
        except RouteRefused as exc:
            raise JevError(str(exc)) from None
        cui = payload_cui(payload)
        eu = not synthetic(cui)
        try:
            route_check(role, tenant_synthetic=not eu, mode=mode)
        except RouteRefused as exc:
            calls.add(
                record(
                    role,
                    payload,
                    mode=mode,
                    tenant_cui=cui,
                    status="refused",
                    reason=str(exc),
                    eu=eu,
                )
            )
            raise JevError(str(exc)) from None
        secret = key(role.key_env) if mode == "live" and role.status == "wired" else None
        if not secret:
            reason = (
                f"{role.key_env} is not set: recorded, not sent"
                if mode == "live" and role.status == "wired"
                else "dry run: recorded, not sent"
            )
            calls.add(
                record(
                    role,
                    payload,
                    mode=mode,
                    tenant_cui=cui,
                    status="recorded",
                    reason=reason,
                    eu=eu,
                )
            )
            raise JevError(f"{role.role_id}: {reason}")
        return _send(role, pack, payload, cui, secret, timeout_s)

    def _send(role, pack, payload, cui, secret, timeout_s) -> dict[str, Any]:
        import httpx

        def failed(reason: str) -> JevError:
            calls.add(
                record(role, payload, mode=mode, tenant_cui=cui, status="failed", reason=reason)
            )
            return JevError(f"{role.role_id}: {reason}")

        body = {
            "model": role.model,
            "state": payload,
            "questions": decision_questions(role),
            "provider": role.provider.model_dump(),
        }
        client = http or httpx.Client(timeout=timeout_s)
        try:
            resp = client.post(
                DECISIONS_URL,
                json=body,
                headers={"Authorization": f"Bearer {secret}"},
                timeout=timeout_s,
            )
        except httpx.HTTPError as exc:
            raise failed(f"OpenRouter unreachable: {type(exc).__name__}") from None
        finally:
            if http is None:  # one we opened: closed after its one call
                client.close()
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code != 200:
            err = (data or {}).get("error") or {}
            msg = str(err.get("message") or "")[:200]
            raise failed(
                f"OpenRouter answered HTTP {resp.status_code} {err.get('code', '')}: {msg}"
            )
        try:
            mapped = map_answers(role, pack, (data or {}).get("answers"))
        except JevError as exc:
            raise failed(str(exc).split(": ", 1)[-1]) from None
        calls.add(
            record(
                role,
                payload,
                mode=mode,
                tenant_cui=cui,
                status="sent",
                reason=f"decided by {data.get('model')} via {data.get('provider')} (OpenRouter)",
                output={
                    "answers": data.get("answers"),
                    "fields": mapped,
                    "usage": data.get("usage"),
                },
            )
        )
        return mapped

    return call


def jev_from_env(cache: Any) -> Jev | None:
    """Jev from ``JEV_BASE_URL`` + ``JEV_API_KEY`` (ARCHITECTURE §14); None if either is unset."""
    base_url, api_key = os.environ.get("JEV_BASE_URL"), os.environ.get("JEV_API_KEY")
    if not (base_url and api_key):
        return None
    return Jev(transport=http_transport(base_url, api_key), cache=cache)


# ----- packs -----


def judge_input(doc: CanonicalDocument, articol: dict[str, Any]) -> dict[str, Any]:
    """What ``v3_judge`` sees: the document with its maps and the articol's accounts.

    No job id, bucket key or earlier Jev answers: the same document asks the same question.
    """
    return {
        "articol": {
            "articol_id": articol["articol_id"],
            "expect_accounts": list((articol.get("reconcile") or {}).get("expect_accounts") or []),
            "write_modules": list(articol.get("write_modules") or []),
        },
        "tenant_cui": doc.tenant.cui,
        "document": doc.model_dump(exclude={"job_id", "tenant", "source", "jev"}),
    }


def v2_input(
    diff: PeriodDiff, axes: dict[str, str], filings: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """What ``v2_declaration_gate`` sees: Layer 1's PeriodDiff, the period's CO.DiT axes and
    the declarations due for them (``filing_id`` + the controls that gate each)."""
    due = sorted(
        (
            {"filing_id": f["filing_id"], "books_gate": list(f.get("books_gate") or [])}
            for f in filings or []
        ),
        key=lambda f: f["filing_id"],
    )
    return {"diff": diff.model_dump(), "axes": dict(sorted(axes.items())), "filings_due": due}


def unjudged(reason: str) -> dict[str, Any]:
    """The Layer 1 verdict when Jev gave no answer: a person is asked."""
    return {"accounts_ok": False, "risk": "unknown", "needs_human": True, "judge": reason}


def make_judge(jev: Jev | None) -> Callable[[CanonicalDocument, dict], dict]:
    """``IngestDeps.judge``: Jev's ``v3_judge`` verdict, or :func:`unjudged`."""

    def judge(doc: CanonicalDocument, articol: dict) -> dict:
        if jev is None:
            return unjudged("not wired")
        try:
            answer = jev.ask("v3_judge", judge_input(doc, articol))
        except JevError as exc:
            return unjudged(str(exc))
        return {**answer.body.model_dump(), "judge": "jev", "input_hash": answer.input_hash}

    return judge


def recon_review_input(doc: CanonicalDocument, det: dict[str, Any]) -> dict[str, Any]:
    """What ``recon_review`` sees: the det verdict and the document, no job id."""
    return {
        "tenant_cui": doc.tenant.cui,
        "det": {k: det.get(k) for k in ("verdict", "reason", "hits", "near", "level")},
        "document": doc.model_dump(exclude={"job_id", "tenant", "source", "jev"}),
    }


def make_recon_review(jev: Jev | None) -> Callable[[Any, Any], Any]:
    """``ReconDeps.review``: Jev's ``recon_review``, or ``abstain`` (det stands)."""
    from poarta_contabila.reconcile import Review

    def review(waiting: Any, det: Any) -> Any:
        if jev is None:
            return Review(verdict="abstain", reason="no reviewer wired")
        try:
            answer = jev.ask("recon_review", recon_review_input(waiting.doc, det.model_dump()))
        except JevError as exc:
            return Review(verdict="abstain", reason=str(exc))
        return Review(verdict=answer.body.verdict, reason="jev")

    return review


def make_v2(
    jev: Jev | None,
    axes: Callable[[str, str], dict[str, str]],
    filings: Callable[[dict[str, str]], list[dict[str, Any]]] = lambda axes: [],
) -> Callable[[PeriodDiff], dict | None]:
    """``CloseDeps.jev_v2``: Jev's suggestion; raises :class:`JevError` when there is none."""

    def v2(diff: PeriodDiff) -> dict | None:
        if jev is None:
            return None
        period_axes = axes(diff.cui, diff.period)
        answer = jev.ask("v2_declaration_gate", v2_input(diff, period_axes, filings(period_axes)))
        return answer.body.model_dump()

    return v2
