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

The wire (endpoint, auth, request and response shape) is not built: it must be taken from
the official docs and quoted in ``RESEARCH_LOG.md``, and those pages were unreachable from
the build session. Until then :func:`http_transport` refuses every call
(:class:`JevNotDocumented`), which fails closed.
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


PACKS: dict[str, tuple[str, type[Closed]]] = {
    "v3_judge": ("1", V3Judge),
    "v2_declaration_gate": ("1", V2Gate),
}
"""pack → (version, closed output model). A new version never reuses cached answers."""

Transport = Callable[[str, dict[str, Any], float], Any]
"""(pack, input, timeout_s) → the answer as JSON text or a decoded object."""


class JevError(RuntimeError):
    """No usable answer: callers fail closed."""


class JevNotDocumented(JevError):
    """The wire has not been read from the official docs; nothing is sent."""


def input_hash(pack: str, payload: dict[str, Any]) -> str:
    version = PACKS[pack][0]
    body = json.dumps(
        {"pack": pack, "version": version, "input": payload},
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

    def ask(self, pack: str, payload: dict[str, Any]) -> JevAnswer:
        """The validated answer, from the cache or the transport; :class:`JevError` otherwise."""
        if pack not in PACKS:
            raise JevError(f"unknown Jev pack {pack!r}")
        try:
            key = input_hash(pack, payload)
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


def v2_input(diff: PeriodDiff, axes: dict[str, str]) -> dict[str, Any]:
    """What ``v2_declaration_gate`` sees: Layer 1's PeriodDiff and the period's CO.DiT axes."""
    return {"diff": diff.model_dump(), "axes": dict(sorted(axes.items()))}


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


def make_v2(
    jev: Jev | None, axes: Callable[[str, str], dict[str, str]]
) -> Callable[[PeriodDiff], dict | None]:
    """``CloseDeps.jev_v2``: Jev's suggestion; raises :class:`JevError` when there is none."""

    def v2(diff: PeriodDiff) -> dict | None:
        if jev is None:
            return None
        answer = jev.ask("v2_declaration_gate", v2_input(diff, axes(diff.cui, diff.period)))
        return answer.body.model_dump()

    return v2
