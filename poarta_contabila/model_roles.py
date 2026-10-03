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
``live``: a role with a built sender sends, synthetic tenants only: document reading
(Google AI Studio, WP-36), the wired Jev packs (OpenRouter Decisions, WP-20) and the wired
System Two explanations (OpenRouter chat, WP-50); every other role records as in ``dry``."""
CALL_MODES = ("off", "dry", "live")
Route = Literal["openrouter", "google_ai_studio"]
KEY_ENV = {
    "system_one": "OPENROUTER_SYS1_API_KEY",  # Jev: its own key and credit limit (WP-55)
    "system_two": "OPENROUTER_SYS2_API_KEY",
    "document_reading": "GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC",  # direct to AI Studio (WP-36)
}
# WP-36: Google AI Studio takes the bare Gemini id (``gemini-…``), never OpenRouter's
# ``google/…`` form, and only for synthetic tenants (route_check).
_AI_STUDIO_MODEL = re.compile(r"^gemini-[a-z0-9][a-z0-9.\-]*$")
FAMILIES = {
    "system_one": {"jev"},
    "system_two": {"deepseek", "glm", "kimi"},  # kimi: an alternate only (00_LAW §8 A7)
    "document_reading": {"gemini"},
}
# an alternate's family, by its OpenRouter model prefix (A7)
ALTERNATE_FAMILIES = {
    "typesafe": "jev",
    "deepseek": "deepseek",
    "z-ai": "glm",
    "moonshotai": "kimi",
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


class Alternate(Closed):
    """00_LAW §8 A7: an owner-approved pin a role moves to while its main pin's provider fails
    the data policy (``provider_policy.pick``). Exact model, named providers, deny."""

    model: str
    provider: ProviderPin

    @field_validator("model")
    @classmethod
    def _exact(cls, value: str) -> str:
        if not value.strip() or _ALIAS.search(value):
            raise ValueError(f"{value!r} is not an exact model id (no alias, auto or :free)")
        return value


class RateLimit(Closed):
    """A model's quota on its route, per minute (Google counts per project, not per key)."""

    rpm: int = Field(gt=0)
    tpm: int = Field(gt=0)
    rpd: int | None = Field(default=None, gt=0)
    """Requests per day (Pacific day; every attempt counts, a 503 included). None = not yet
    confirmed (`[de confirmat]`): only Google's daily 429 stops it."""


class Tiers(Closed):
    """00_LAW §8 A4: the order Google AI Studio document reading uses its models in.
    ``everyday``: the most requests a day, read first. ``strong``: more capable, fewer a day;
    for hard documents, an asked re-read, or a second run on a read that does not tie out."""

    everyday: list[str] = Field(min_length=1)
    strong: list[str] = Field(min_length=1)
    reserve: list[str] = Field(default_factory=list)
    """00_LAW §8 A6: read with only on a day an operator chose them, after the other tiers."""

    @property
    def all(self) -> list[str]:
        return [*self.everyday, *self.strong, *self.reserve]


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
    tiers: Tiers | None = None
    """00_LAW §8 A4: Google AI Studio document reading only; ``model`` is its first everyday
    model. Never on another route."""
    rate_limits: dict[str, RateLimit] = Field(default_factory=dict)
    """Per model id: the free-tier quota the sender keeps under (A3, A4)."""
    route: Route = "openrouter"
    provider: ProviderPin = Field(default_factory=ProviderPin)
    alternates: list[Alternate] = Field(default_factory=list)
    """00_LAW §8 A7: approved pins, in order, used only while the main pin fails the data
    policy (OpenRouter roles; WP-53)."""
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


def ai_studio_model_ok(model: str) -> bool:
    """A bare Google AI Studio id (``gemini-…``), no alias (WP-36)."""
    return bool(_AI_STUDIO_MODEL.match(model)) and not _ALIAS.search(model)


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
        if role.tiers is not None:
            if role.route != "google_ai_studio":
                raise ValueError(
                    f"role {role.role_id!r}: model tiers are only for Google AI Studio"
                    " document reading (00_LAW §8 A4)"
                )
            models = role.tiers.all
            if len(set(models)) != len(models):
                raise ValueError(f"role {role.role_id!r}: a model is listed twice in tiers")
            for m in models:
                if not ai_studio_model_ok(m):
                    raise ValueError(
                        f"role {role.role_id!r}: {m!r} is not an exact Google AI Studio model id"
                        " (gemini-…, without google/, no alias)"
                    )
            if role.model != role.tiers.everyday[0]:
                raise ValueError(f"role {role.role_id!r}: model is the first everyday model")
        if role.alternates:
            if role.route != "openrouter" or role.model is None:
                raise ValueError(f"role {role.role_id!r}: alternates are for OpenRouter roles")
            pins = [(role.model, tuple(role.provider.only))] + [
                (a.model, tuple(a.provider.only)) for a in role.alternates
            ]
            if len(set(pins)) != len(pins):
                raise ValueError(f"role {role.role_id!r}: a pin is listed twice")
            if not all(a.provider.only for a in role.alternates):
                raise ValueError(f"role {role.role_id!r}: an alternate names its provider")
            for a in role.alternates:
                fam = a.model.split("/")[0]
                if ALTERNATE_FAMILIES.get(fam) not in FAMILIES[role.system]:
                    raise ValueError(
                        f"role {role.role_id!r}: alternate {a.model!r}"
                        f" is not a {role.system} family"
                    )
        if role.rate_limits and role.route != "google_ai_studio":
            raise ValueError(f"role {role.role_id!r}: rate limits are Google AI Studio's")
        if role.route == "google_ai_studio" and role.model is not None:
            used = role.tiers.all if role.tiers else [role.model]
            missing = [m for m in used if m not in role.rate_limits]
            if missing:
                raise ValueError(f"role {role.role_id!r}: no rate limit for {missing}")
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
        model=route.model if route else (None if eu else role.model),
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

    def sent(self, role_id: str, input_hash: str) -> ModelCall | None:
        """The latest ``sent`` call of *role_id* for this input (WP-50)."""
        rows = [
            c
            for c in self.rows
            if c.role_id == role_id and c.input_hash == input_hash and c.status == "sent"
        ]
        return rows[-1] if rows else None


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

    def sent(self, role_id: str, input_hash: str) -> ModelCall | None:
        """The latest ``sent`` call of *role_id* for this input (WP-50)."""
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT body FROM domain.model_calls WHERE role_id = %s"
                " AND body->>'input_hash' = %s AND body->>'status' = 'sent'"
                " ORDER BY at DESC LIMIT 1",
                (role_id, input_hash),
            ).fetchone()
        return ModelCall.model_validate(row[0], strict=False) if row else None


# ----- shadow roles: observed at their place in the flow (WP-26) -----


@dataclass
class ModelGateway:
    """Where a ``shadow`` role would be called, record what it would be sent (dry only).

    Never blocks the flow: any failure here is logged and the node goes on. A shadow role's
    answer would decide nothing. A node that runs again on resume records the same input once
    (``seen``). A wired System Two role (WP-50) is sent in ``live`` (``explain.send``) and its
    explanation shown next to the question (:meth:`explanation`); it never feeds a node.
    """

    roles: dict[str, ModelRole]
    calls: Any
    mode: str = "off"
    synthetic: Any = lambda cui: False  # Callable[[str | None], bool]
    http: Any = None  # httpx.Client for the System Two sender (tests)
    key: Any = None  # Callable[[str], str | None]; None = os.environ.get
    router: Any = None  # provider_policy.Router: the pin the data policy allows (WP-53)

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

    def explanation(self, question: Any, tenant_cui: str | None) -> dict[str, Any] | None:
        """The sent explanation of the question a person sees now, if there is one."""
        if not isinstance(question, dict) or not isinstance(question.get("kind"), str):
            return None
        kind = question["kind"]
        payload = {k: v for k, v in question.items() if k not in ("kind", "error")}
        try:
            for role in self.roles.values():
                if role.system != "system_two" or kind not in role.hitl_kinds:
                    continue
                probe = record(
                    role,
                    {"kind": kind, "question": payload},
                    mode=self.mode,
                    tenant_cui=tenant_cui,
                    status="recorded",
                    reason="",
                )
                call = self.calls.sent(role.role_id, probe.input_hash)
                if call is not None and call.output is not None:
                    keep = ("explanation", "facts_cited", "missing", "served_by")
                    return {
                        "role_id": role.role_id,
                        **{k: call.output.get(k) for k in keep},
                    }
        except Exception:
            log.exception("model gateway: no explanation for %s", kind)
        return None

    def _observe(self, role_id: str, payload: dict[str, Any], tenant_cui: str | None) -> None:
        role = self.roles.get(role_id)
        if self.mode not in ("dry", "live") or role is None:
            return
        # shadow roles; and a wired document-reading role where its reader is not called
        reading = role.status == "wired" and role.system == "document_reading"
        explains = role.status == "wired" and role.system == "system_two"
        if role.status != "shadow" and not reading and not explains:
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
            if explains and self.mode == "live":
                self._explain(role, payload, tenant_cui)
                return
            call = record(
                role,
                payload,
                mode=self.mode,
                tenant_cui=tenant_cui,
                status="recorded",
                reason=(
                    "dry run: recorded, not sent"
                    if explains
                    else "shadow: recorded, not sent; its answer would decide nothing"
                ),
                eu=not synthetic,
            )
        if not self.calls.seen(role_id, call.input_hash):
            self.calls.add(call)

    def _explain(self, role: ModelRole, payload: dict[str, Any], tenant_cui: str | None) -> None:
        """Send a wired System Two role once per question (synthetic tenant, live)."""
        import os

        from poarta_contabila.explain import ExplainError, PolicyRefused, send

        def add(status: Literal["recorded", "sent", "failed"], reason: str, output=None) -> None:
            self.calls.add(
                record(
                    used,
                    payload,
                    mode=self.mode,
                    tenant_cui=tenant_cui,
                    status=status,
                    reason=reason,
                    output=output,
                )
            )

        probe = record(
            role, payload, mode=self.mode, tenant_cui=tenant_cui, status="sent", reason=""
        )
        if self.calls.sent(role.role_id, probe.input_hash) is not None:
            return  # explained already: a resume does not pay twice
        used = role
        secret = (self.key or os.environ.get)(role.key_env)
        if not secret:
            if not self.calls.seen(role.role_id, probe.input_hash):
                add("recorded", f"{role.key_env} is not set: recorded, not sent")
            return
        p = self.router.pick(role) if self.router is not None else None
        for attempt in (1, 2):
            if p is not None and p.model is None:
                add("failed", p.reason)
                return
            used = role.model_copy(update={"model": p.model}) if p is not None else role
            note = f" [{p.reason}]" if p is not None and p.reason else ""
            try:
                out = send(used, payload, secret, http=self.http, provider=p and p.provider)
            except PolicyRefused as exc:
                add("failed", str(exc) + note)
                again = (
                    self.router.pick(role)
                    if attempt == 1 and self.router is not None and self.router.refused(str(exc))
                    else p
                )
                if again == p:
                    return
                p = again
                continue
            except ExplainError as exc:
                add("failed", str(exc) + note)
                return
            add("sent", f"explained by {out['served_by']} (OpenRouter){note}", out)
            return
