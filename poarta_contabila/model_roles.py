"""Model roles (00_LAW §3 invariant 5; catalog ``ArticoleModelRoles``): who may call which model.

A model acts only inside a node, through a role row that pins one exact model. Before any
call, :func:`route_check` refuses (fail closed):

- a role whose ``model`` is not chosen yet (``null`` in the catalog);
- a client tenant on any route but the role's ``eu_route`` (synthetic tenants only until the
  EU host is set);
- calls switched off (``MODEL_CALLS=off``, the default).

``MODEL_CALLS=dry`` records exactly what a role would be sent (role, model, provider pin,
input) in ``domain.model_calls`` and sends nothing; the caller then fails closed as if no
answer came (a person is asked). The live sender is not built here (BUILD WP-20 / WP-24).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from poarta_contabila.types import Closed, Slug

System = Literal["system_one", "system_two", "document_reading"]
CallMode = Literal["off", "dry"]
KEY_ENV = {
    "system_one": "OPENROUTER_JEV_API_KEY",
    "system_two": "OPENROUTER_SYS2_API_KEY",
    "document_reading": "OPENROUTER_OCR_API_KEY",
}
FAMILIES = {
    "system_one": {"jev"},
    "system_two": {"deepseek", "glm"},
    "document_reading": {"gemini"},
}
_ALIAS = re.compile(r"(^openrouter/auto$|latest|:free$|^auto$)", re.IGNORECASE)


class RouteRefused(RuntimeError):
    """The role may not be called now; nothing was sent."""


class ProviderPin(Closed):
    """OpenRouter provider routing for a role: named providers only, never a fallback."""

    only: list[str] = Field(default_factory=list)
    allow_fallbacks: Literal[False] = False
    data_collection: Literal["deny"] = "deny"


class ModelRole(Closed):
    role_id: Slug
    graph_id: Slug
    node: Slug
    system: System
    family: str | None = None
    decision_id: str | None = None
    pack: str | None = None
    hitl_kinds: list[str] = Field(default_factory=list)
    output: str
    status: Literal["wired", "not_wired"]
    model: str | None = None
    route: Literal["openrouter"] = "openrouter"
    provider: ProviderPin = Field(default_factory=ProviderPin)
    data: Literal["synthetic_only"] = "synthetic_only"
    eu_route: str | None = None
    note: str | None = None

    @field_validator("model")
    @classmethod
    def _exact(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip() or _ALIAS.search(value):
            raise ValueError(f"{value!r} is not an exact model id (no alias, auto or :free)")
        return value

    @property
    def key_env(self) -> str:
        return KEY_ENV[self.system]


def load_roles(doc: dict[str, Any]) -> dict[str, ModelRole]:
    """The catalog's role rows, validated; ``ValueError`` names the first bad row."""
    defaults = doc.get("defaults") or {}
    out: dict[str, ModelRole] = {}
    for row in doc.get("roles") or []:
        if "fallback_models" in row or "models" in row:
            raise ValueError(f"role {row.get('role_id')!r}: fallback model lists are forbidden")
        merged = {
            "provider": defaults.get("provider") or {},
            "eu_route": defaults.get("eu_route"),
            **row,
        }
        role = ModelRole.model_validate(merged)
        family = role.family or ("jev" if role.system == "system_one" else "gemini")
        if role.system == "system_two" and role.family is None:
            raise ValueError(f"role {role.role_id!r}: a System Two role names its family")
        if family not in FAMILIES[role.system]:
            raise ValueError(f"role {role.role_id!r}: family {family!r} is not {role.system}")
        if role.status == "wired" and role.pack is None:
            raise ValueError(f"role {role.role_id!r}: a wired role names its pack")
        if role.role_id in out:
            raise ValueError(f"duplicate role_id {role.role_id!r}")
        out[role.role_id] = role
    return out


def role_for_pack(roles: dict[str, ModelRole], pack: str) -> ModelRole:
    found = [r for r in roles.values() if r.pack == pack]
    if len(found) != 1:
        raise RouteRefused(f"no single model role for pack {pack!r}")
    return found[0]


def route_check(role: ModelRole, *, tenant_synthetic: bool, mode: str) -> None:
    """Raise :class:`RouteRefused` unless *role* may be called now (see module docstring)."""
    if mode not in ("dry",):
        raise RouteRefused(f"{role.role_id}: model calls are {mode!r}")
    if role.model is None:
        raise RouteRefused(f"{role.role_id}: no model chosen in ArticoleModelRoles")
    if not tenant_synthetic and role.eu_route is None:
        raise RouteRefused(f"{role.role_id}: a client tenant needs the EU route; none is set")


# ----- what was (or would be) sent -----


class ModelCall(Closed):
    call_id: str
    role_id: str
    model: str | None
    route: str
    provider: ProviderPin
    mode: str
    tenant_cui: str | None
    pack: str | None
    input_hash: str
    input: dict[str, Any]
    status: Literal["recorded", "refused"]
    reason: str
    at: str


def record(
    role: ModelRole,
    payload: dict[str, Any],
    *,
    mode: str,
    tenant_cui: str | None,
    status: Literal["recorded", "refused"],
    reason: str,
) -> ModelCall:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return ModelCall(
        call_id=str(uuid.uuid4()),
        role_id=role.role_id,
        model=role.model,
        route=role.route,
        provider=role.provider,
        mode=mode,
        tenant_cui=tenant_cui,
        pack=role.pack,
        input_hash=hashlib.sha256(body.encode()).hexdigest(),
        input=payload,
        status=status,
        reason=reason,
        at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


@dataclass
class InMemoryModelCallStore:
    rows: list[ModelCall] = field(default_factory=list)

    def add(self, call: ModelCall) -> None:
        self.rows.append(call)

    def recent(self, role_id: str | None = None, limit: int = 50) -> list[ModelCall]:
        rows = [c for c in self.rows if role_id in (None, c.role_id)]
        return list(reversed(rows))[:limit]


class PostgresModelCallStore:
    """``domain.model_calls``: one row per recorded (or refused) call."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def add(self, call: ModelCall) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.model_calls (call_id, role_id, at, body)"
                " VALUES (%s, %s, %s, %s)",
                (call.call_id, call.role_id, call.at, call.model_dump_json()),
            )

    def recent(self, role_id: str | None = None, limit: int = 50) -> list[ModelCall]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT body FROM domain.model_calls WHERE (%s::text IS NULL OR role_id = %s)"
                " ORDER BY at DESC, call_id LIMIT %s",
                (role_id, role_id, limit),
            ).fetchall()
        return [ModelCall.model_validate(r[0], strict=False) for r in rows]
