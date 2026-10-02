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
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from poarta_contabila.types import Closed, Slug

System = Literal["system_one", "system_two", "document_reading"]
CallMode = Literal["off", "dry", "live"]
"""``off``: nothing. ``dry``: every role records what it would be sent, nothing is sent.
``live``: a role with a built sender sends (today only document reading, synthetic tenants
only, WP-36); every other role records as in ``dry``."""
CALL_MODES = ("off", "dry", "live")
Route = Literal["openrouter", "google_ai_studio"]
KEY_ENV = {
    "system_one": "OPENROUTER_JEV_API_KEY",
    "system_two": "OPENROUTER_SYS2_API_KEY",
    "document_reading": "GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC",  # direct to AI Studio (WP-36)
}
# WP-36: Google AI Studio takes the bare Gemini id (``gemini-…``), never OpenRouter's
# ``google/…`` form, and only for synthetic tenants (route_check).
_AI_STUDIO_MODEL = re.compile(r"^gemini-[a-z0-9][a-z0-9.\-]*$")
FAMILIES = {
    "system_one": {"jev"},
    "system_two": {"deepseek", "glm"},
    "document_reading": {"gemini"},
}
log = logging.getLogger(__name__)
_ALIAS = re.compile(r"(^openrouter/auto$|latest|:free$|^auto$)", re.IGNORECASE)


# WP-35: the EU route's regions, by provider — an explicit list, never a prefix. Google's
# europe-west2 (London) and europe-west6 (Zurich) are outside the EU; "global" has no residency.
EU_LOCATIONS: dict[str, frozenset[str]] = {
    "vertex": frozenset(
        {
            "europe-central2",  # Warsaw
            "europe-north1",  # Finland
            "europe-north2",  # Stockholm
            "europe-southwest1",  # Madrid
            "europe-west1",  # Belgium
            "europe-west3",  # Frankfurt
            "europe-west4",  # Netherlands
            "europe-west8",  # Milan
            "europe-west9",  # Paris
            "europe-west10",  # Berlin
            "europe-west12",  # Turin
        }
    ),
    "scaleway": frozenset({"fr-par", "nl-ams", "pl-waw"}),
}
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class EuRoute(Closed):
    """The only route a client tenant's data may take (00_LAW §3 invariant 5; WP-35).

    Who serves which family is the owner's decision (``docs/EU_VERTEX_SETUP.md``); this only
    makes whatever is written checkable: an EU region of that provider, one exact model, and
    the variables that hold the credential (values never in the catalog).
    """

    provider: Literal["vertex", "scaleway"]
    location: str
    model: str
    key_env: str  # the credential: a sealed variable (e.g. the service-account JSON)
    project_env: str | None = None  # Vertex: the variable holding the GCP project id

    @model_validator(mode="after")
    def _eu_only(self) -> EuRoute:
        allowed = EU_LOCATIONS[self.provider]
        if self.location not in allowed:
            raise ValueError(
                f"eu_route: {self.location!r} is not an EU region of {self.provider}"
                f" ({', '.join(sorted(allowed))})"
            )
        if not self.model.strip() or _ALIAS.search(self.model):
            raise ValueError(f"eu_route: {self.model!r} is not an exact model id")
        for name in (self.key_env, self.project_env):
            if name is not None and not _ENV_NAME.match(name):
                raise ValueError(f"eu_route: {name!r} is not a variable name")
        if self.provider == "vertex" and self.project_env is None:
            raise ValueError("eu_route: a vertex route names its project_env")
        return self

    @property
    def label(self) -> str:
        return f"eu/{self.provider}/{self.location}"


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
    status: Literal["wired", "shadow", "not_wired"]
    """wired: its answer feeds the node (fail closed). shadow: observed at its place in the
    flow (MODEL_CALLS=dry records it) but its answer would decide nothing. not_wired: no call
    site yet."""
    model: str | None = None
    route: Route = "openrouter"
    provider: ProviderPin = Field(default_factory=ProviderPin)
    data: Literal["synthetic_only"] = "synthetic_only"
    eu_route: EuRoute | None = None
    note: str | None = None
    card: dict[str, Any] = Field(default_factory=dict)
    """The merged role card (system base + role); see :func:`check_card`."""

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

    @property
    def card_hash(self) -> str:
        body = json.dumps(self.card, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(body.encode()).hexdigest()

    def questions(self) -> dict[str, Any] | None:
        """System One: the question set this role asks (as written in its card)."""
        return self.card.get("questions") if self.system == "system_one" else None


# ----- role cards (WP-25) -----

_QUESTION_TYPES = {"noul", "choice", "score"}
_SYS2_FIELDS = ["explanation", "facts_cited", "missing"]
_DECISION_WORDS = {"recommendation", "action", "decision", "verdict", "approve", "file", "gate"}
_PERSONA = re.compile(r"\byou are (an?|the) ", re.IGNORECASE)


def _fail(role_id: str, msg: str) -> None:
    raise ValueError(f"role {role_id!r} card: {msg}")


def check_card(role: ModelRole, pack_fields: set[str] | None) -> None:
    """Refuse a card the role cannot honour (``ValueError``).

    System One: every question has a known type; a choice names its criteria (inline or
    ``criteria_from``); a score has levels; ``fields`` names only asked questions (or a
    choice's ``.confidence``) and, for a built pack, covers exactly its closed model's fields;
    thresholds are probabilities. Document reading: instructions and an output shape. System
    Two: a task, the base limits, exactly the output fields ``explanation, facts_cited,
    missing`` (no decision field) and no persona.
    """
    c, rid = role.card, role.role_id
    bad = _non_string_key(c)
    if bad is not None:
        _fail(rid, f"key {bad!r} is not text (YAML reads yes/no/on/off/true/false as booleans)")
    if role.system == "system_one":
        questions = c.get("questions")
        if not isinstance(questions, dict) or not questions:
            _fail(rid, "a System One card asks at least one question")
        for name, q in questions.items():
            if not isinstance(q, dict) or q.get("type") not in _QUESTION_TYPES:
                _fail(rid, f"question {name!r} has no type among {sorted(_QUESTION_TYPES)}")
            if q["type"] == "choice" and not (q.get("criteria") or q.get("criteria_from")):
                _fail(rid, f"choice {name!r} names no criteria")
            if q["type"] == "score" and not q.get("criteria"):
                _fail(rid, f"score {name!r} has no levels")
        fields = c.get("fields")
        if not isinstance(fields, dict) or not fields:
            _fail(rid, "names which closed field each question fills (fields)")
        for field_name, source in fields.items():
            base, _, attr = str(source).partition(".")
            if base not in questions or attr not in ("", "confidence"):
                _fail(rid, f"field {field_name!r} reads {source!r}, which is not asked")
        if pack_fields is not None and set(fields) != pack_fields:
            _fail(rid, f"fields {sorted(fields)} must be the pack's {sorted(pack_fields)}")
        for key, value in (c.get("thresholds") or {}).items():
            if not isinstance(value, int | float) or not 0 < value < 1:
                _fail(rid, f"threshold {key!r} must be between 0 and 1")
    elif role.system == "document_reading":
        if not c.get("instructions") or not c.get("output"):
            _fail(rid, "a document-reading card has instructions and an output shape")
    else:
        if not c.get("task") or not c.get("limits"):
            _fail(rid, "a System Two card has a task and limits")
        if c.get("output_fields") != _SYS2_FIELDS:
            _fail(rid, f"output_fields must be exactly {_SYS2_FIELDS}")
        if _DECISION_WORDS & {str(f).lower() for f in c.get("output_fields") or []}:
            _fail(rid, "no decision field in a System Two output")
        text = json.dumps(c, ensure_ascii=False)
        if _PERSONA.search(text) or "persona" in c:
            _fail(rid, "no persona: say who reads, what to do and what never to do")


def _non_string_key(value: Any) -> Any:
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                return k
            found = _non_string_key(v)
            if found is not None:
                return found
    elif isinstance(value, list):
        for v in value:
            found = _non_string_key(v)
            if found is not None:
                return found
    return None


def brief(role: ModelRole) -> str | None:
    """The card rendered as the text the model is given (deterministic): System Two and
    document reading; System One sends its question set instead."""
    if role.system == "document_reading":
        return _reading_brief(role)
    if role.system != "system_two":
        return None
    c = role.card
    lines = [f"Reader: {c['audience'].strip()}", f"Task: {c['task'].strip()}", "Never:"]
    lines += [f"- {limit}" for limit in c["limits"]]
    lines.append(f"Language: {c.get('language', '').strip()}")
    if c.get("terms"):
        lines.append("Terms:")
        lines += [f"- {t}" for t in c["terms"]]
    lines.append(f"Output: {c.get('output_rule', '').strip()}")
    return "\n".join(lines)


def _reading_brief(role: ModelRole) -> str:
    c = role.card
    lines = [f"Task: {str(c.get('task', '')).strip()}", "Rules:"]
    lines += [f"- {rule}" for rule in c.get("instructions") or []]
    lines.append("Output: one JSON object with exactly these keys:")
    lines += [f"- {key}: {shape}" for key, shape in (c.get("output") or {}).items()]
    return "\n".join(lines)


def load_roles(doc: dict[str, Any]) -> dict[str, ModelRole]:
    """The catalog's role rows, validated; ``ValueError`` names the first bad row."""
    from poarta_contabila.jev import PACKS  # the closed models a wired card must fill

    defaults = doc.get("defaults") or {}
    systems = doc.get("systems") or {}
    out: dict[str, ModelRole] = {}
    for row in doc.get("roles") or []:
        if "fallback_models" in row or "models" in row:
            raise ValueError(f"role {row.get('role_id')!r}: fallback model lists are forbidden")
        base_card = (systems.get(row.get("system")) or {}).get("card") or {}
        merged = {
            "provider": defaults.get("provider") or {},
            "eu_route": defaults.get("eu_route"),
            **row,
            "card": {**base_card, **(row.get("card") or {})},
        }
        role = ModelRole.model_validate(merged)
        family = role.family or ("jev" if role.system == "system_one" else "gemini")
        if role.system == "system_two" and role.family is None:
            raise ValueError(f"role {role.role_id!r}: a System Two role names its family")
        if family not in FAMILIES[role.system]:
            raise ValueError(f"role {role.role_id!r}: family {family!r} is not {role.system}")
        jev_wired = role.status == "wired" and role.system == "system_one"
        if jev_wired and role.pack is None:
            raise ValueError(f"role {role.role_id!r}: a wired role names its pack")
        if jev_wired and role.pack not in PACKS:
            raise ValueError(f"role {role.role_id!r}: pack {role.pack!r} is not built")
        if role.route == "google_ai_studio":
            if role.system != "document_reading":
                raise ValueError(
                    f"role {role.role_id!r}: only document reading goes direct to Google AI Studio"
                )
            if role.provider.only:
                raise ValueError(f"role {role.role_id!r}: provider pins are OpenRouter's")
            if role.model is not None and not _AI_STUDIO_MODEL.match(role.model):
                raise ValueError(
                    f"role {role.role_id!r}: {role.model!r} is not a Google AI Studio model id"
                    " (gemini-…, without google/)"
                )
        if role.role_id in out:
            raise ValueError(f"duplicate role_id {role.role_id!r}")
        pack_fields = set(PACKS[role.pack][1].model_fields) if jev_wired else None
        check_card(role, pack_fields)
        out[role.role_id] = role
    return out


def role_for_pack(roles: dict[str, ModelRole], pack: str) -> ModelRole:
    found = [r for r in roles.values() if r.pack == pack]
    if len(found) != 1:
        raise RouteRefused(f"no single model role for pack {pack!r}")
    return found[0]


def route_check(role: ModelRole, *, tenant_synthetic: bool, mode: str) -> None:
    """Raise :class:`RouteRefused` unless *role* may be called now (see module docstring)."""
    if mode not in ("dry", "live"):
        raise RouteRefused(f"{role.role_id}: model calls are {mode!r}")
    if not tenant_synthetic:  # client data: the EU route or nothing
        if role.eu_route is None:
            raise RouteRefused(f"{role.role_id}: a client tenant needs the EU route; none is set")
        return
    if role.model is None:
        raise RouteRefused(f"{role.role_id}: no model chosen in ArticoleModelRoles")


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
    card_hash: str
    input_hash: str
    input: dict[str, Any]
    questions: dict[str, Any] | None = None  # System One: the question set that would be asked
    status: Literal["recorded", "refused", "sent", "failed"]
    reason: str
    at: str
    output: dict[str, Any] | None = None  # a sent call: what came back (shape, not bytes)


def record(
    role: ModelRole,
    payload: dict[str, Any],
    *,
    mode: str,
    tenant_cui: str | None,
    status: Literal["recorded", "refused", "sent", "failed"],
    reason: str,
    eu: bool = False,
    output: dict[str, Any] | None = None,
) -> ModelCall:
    """*eu*: a client tenant's call, which goes by the role's ``eu_route`` (when set)."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    route = role.eu_route if eu else None
    return ModelCall(
        call_id=str(uuid.uuid4()),
        role_id=role.role_id,
        model=route.model if route else role.model,
        route=route.label if route else ("eu/none" if eu else role.route),
        provider=role.provider,
        mode=mode,
        tenant_cui=tenant_cui,
        pack=role.pack,
        card_hash=role.card_hash,
        input_hash=hashlib.sha256(body.encode()).hexdigest(),
        input=payload,
        questions=role.questions(),
        status=status,
        reason=reason,
        at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        output=output,
    )


@dataclass
class InMemoryModelCallStore:
    rows: list[ModelCall] = field(default_factory=list)

    def add(self, call: ModelCall) -> None:
        self.rows.append(call)

    def seen(self, role_id: str, input_hash: str) -> bool:
        return any(c.role_id == role_id and c.input_hash == input_hash for c in self.rows)

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

    def seen(self, role_id: str, input_hash: str) -> bool:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT 1 FROM domain.model_calls WHERE role_id = %s"
                " AND body->>'input_hash' = %s LIMIT 1",
                (role_id, input_hash),
            ).fetchone()
        return row is not None

    def recent(self, role_id: str | None = None, limit: int = 50) -> list[ModelCall]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT body FROM domain.model_calls WHERE (%s::text IS NULL OR role_id = %s)"
                " ORDER BY at DESC, call_id LIMIT %s",
                (role_id, role_id, limit),
            ).fetchall()
        return [ModelCall.model_validate(r[0], strict=False) for r in rows]


# ----- shadow roles: observed at their place in the flow (WP-26) -----


@dataclass
class ModelGateway:
    """Where a ``shadow`` role would be called, record what it would be sent (dry only).

    Never blocks the flow: any failure here is logged and the node goes on. Nothing is sent;
    the role's answer would decide nothing. A node that runs again on resume records the same
    input once (``seen``).
    """

    roles: dict[str, ModelRole]
    calls: Any
    mode: str = "off"
    synthetic: Any = lambda cui: False  # Callable[[str | None], bool]

    def observe(self, role_id: str, payload: dict[str, Any], tenant_cui: str | None) -> None:
        try:
            self._observe(role_id, payload, tenant_cui)
        except Exception:
            log.exception("model gateway: %s not recorded", role_id)

    def observe_question(self, kind: str, payload: dict[str, Any], tenant_cui: str | None) -> None:
        """The System Two roles that would explain a person's question of *kind*."""
        for role in self.roles.values():
            if role.system == "system_two" and kind in role.hitl_kinds:
                self.observe(role.role_id, {"kind": kind, "question": payload}, tenant_cui)

    def _observe(self, role_id: str, payload: dict[str, Any], tenant_cui: str | None) -> None:
        role = self.roles.get(role_id)
        if self.mode not in ("dry", "live") or role is None:
            return
        # shadow roles; and a wired document-reading role where its reader is not called
        reading = role.status == "wired" and role.system == "document_reading"
        if role.status != "shadow" and not reading:
            return
        synthetic = self.synthetic(tenant_cui)
        try:
            route_check(role, tenant_synthetic=synthetic, mode=self.mode)
        except RouteRefused as exc:
            call = record(
                role,
                payload,
                mode=self.mode,
                tenant_cui=tenant_cui,
                status="refused",
                reason=str(exc),
                eu=not synthetic,
            )
        else:
            call = record(
                role,
                payload,
                mode=self.mode,
                tenant_cui=tenant_cui,
                status="recorded",
                reason="shadow: recorded, not sent; its answer would decide nothing",
                eu=not synthetic,
            )
        if not self.calls.seen(role_id, call.input_hash):
            self.calls.add(call)
