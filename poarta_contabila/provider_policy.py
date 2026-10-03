"""Provider data policies and the approved alternates (00_LAW §8 A7; WP-53).

Every OpenRouter role sends ``data_collection: deny``: OpenRouter routes only to endpoints
whose provider neither trains on nor keeps prompts, and refuses (HTTP 404, "data policy")
when none is left. This module notices that before the work does:

- **Policies**: OpenRouter's provider list (``POLICY_URL``) is read once a day and right after
  a call is refused for its data policy, into ``domain.provider_policies``. A provider
  *passes* when it neither trains on prompts nor retains them. Not yet read = passes
  (OpenRouter still enforces ``deny`` on every call).
- **Pick** (:func:`pick`): a role uses its main pin while all its providers pass, else the
  first owner-approved ``alternates`` entry that passes, automatically and back again when the
  main pin passes. Nothing outside the catalog is ever used.
- **Operator choice** (``domain.model_role_choices``) when no pin passes: ``wait`` (calls fail
  closed as before), ``pause`` (the role records only) or ``allow_synthetic`` until a date:
  the main pin with ``data_collection: allow``, synthetic tenants only (a client tenant never
  reaches a sender), and it expires by itself.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field

from poarta_contabila.types import Closed

log = logging.getLogger(__name__)
POLICY_URL = "https://openrouter.ai/api/frontend/v1/all-providers"
REFRESH_SECONDS = 24 * 3600
DATA_POLICY_REFUSAL = "data policy"  # in OpenRouter's 404 message


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProviderPolicy(Closed):
    slug: str
    training: bool | None = None
    retains_prompts: bool | None = None
    checked_at: str

    @property
    def passes(self) -> bool:
        return self.training is False and self.retains_prompts is False

    def why(self) -> str:
        parts = [
            "trains on prompts" if self.training is not False else None,
            "keeps prompts" if self.retains_prompts is not False else None,
        ]
        return f"{self.slug} " + " and ".join(p for p in parts if p)


class RoleChoice(Closed):
    role_id: str
    choice: Literal["wait", "pause", "allow_synthetic"]
    until: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    operator: str | None = None
    at: str

    def active(self, today: str) -> bool:
        return self.choice != "allow_synthetic" or (self.until is not None and today <= self.until)


@dataclass(frozen=True)
class Pick:
    model: str | None
    provider: dict[str, Any] | None  # the ProviderPin as sent
    on: str  # "main" | "alternate N" | "operator choice" | "none"
    reason: str


def parse(data: Any, checked_at: str | None = None) -> list[ProviderPolicy]:
    """OpenRouter's provider list → policies (rows without a slug are skipped)."""
    rows = data.get("data", data) if isinstance(data, dict) else data
    at = checked_at or _now()
    out = []
    for p in rows or []:
        if not isinstance(p, dict) or not p.get("slug"):
            continue
        dp = p.get("dataPolicy") or {}
        out.append(
            ProviderPolicy(
                slug=p["slug"],
                training=dp.get("training"),
                retains_prompts=dp.get("retainsPrompts"),
                checked_at=at,
            )
        )
    return out


def fetch(http: Any = None) -> list[ProviderPolicy]:
    """Read OpenRouter's provider list now (``httpx`` errors propagate)."""
    import httpx

    client = http if http is not None else httpx.Client(timeout=30)
    try:
        resp = client.get(POLICY_URL)
        resp.raise_for_status()
        return parse(resp.json())
    finally:
        if http is None:
            client.close()


def pick(
    role: Any,
    policies: Any,
    choice: RoleChoice | None = None,
    today: str | None = None,
) -> Pick:
    """Which pin *role* is sent on now (see the module docstring)."""
    today = today or _now()[:10]
    if choice is not None and choice.active(today) and choice.choice == "pause":
        return Pick(None, None, "none", f"{role.role_id}: paused by the operator")
    pins = [(role.model, role.provider)] + [(a.model, a.provider) for a in role.alternates]
    failing: list[str] = []
    for i, (model, provider) in enumerate(pins):
        bad = [
            pol.why()
            for slug in provider.only
            if (pol := policies.get(slug)) is not None and not pol.passes
        ]
        if not bad:
            on = "main" if i == 0 else f"alternate {i}"
            reason = "" if i == 0 else f"on {on}: " + "; ".join(failing)
            return Pick(model, provider.model_dump(), on, reason)
        failing.extend(bad)
    if choice is not None and choice.active(today) and choice.choice == "allow_synthetic":
        pin = {**role.provider.model_dump(), "data_collection": "allow"}
        return Pick(
            role.model,
            pin,
            "operator choice",
            f"operator allowed {'; '.join(failing)} for synthetic data until {choice.until}",
        )
    return Pick(None, None, "none", f"{role.role_id}: no passing model: " + "; ".join(failing))


# ----- stores -----


@dataclass
class InMemoryPolicyStore:
    rows: dict[str, ProviderPolicy] = field(default_factory=dict)

    def put_all(self, rows: list[ProviderPolicy]) -> None:
        self.rows.update({r.slug: r for r in rows})

    def get(self, slug: str) -> ProviderPolicy | None:
        return self.rows.get(slug)

    def checked_at(self) -> str | None:
        return max((r.checked_at for r in self.rows.values()), default=None)


class PostgresPolicyStore:
    """``domain.provider_policies``: one row per provider, the latest read."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def put_all(self, rows: list[ProviderPolicy]) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            for r in rows:
                conn.execute(
                    "INSERT INTO domain.provider_policies (slug, body) VALUES (%s, %s)"
                    " ON CONFLICT (slug) DO UPDATE SET body = EXCLUDED.body",
                    (r.slug, r.model_dump_json()),
                )

    def get(self, slug: str) -> ProviderPolicy | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT body FROM domain.provider_policies WHERE slug = %s", (slug,)
            ).fetchone()
        return ProviderPolicy.model_validate(row[0], strict=False) if row else None

    def checked_at(self) -> str | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT max(body->>'checked_at') FROM domain.provider_policies"
            ).fetchone()
        return row[0] if row else None


@dataclass
class InMemoryRoleChoiceStore:
    rows: list[RoleChoice] = field(default_factory=list)

    def put(self, choice: RoleChoice) -> None:
        self.rows.append(choice)

    def latest(self, role_id: str) -> RoleChoice | None:
        found = [c for c in self.rows if c.role_id == role_id]
        return found[-1] if found else None


class PostgresRoleChoiceStore:
    """``domain.model_role_choices``: every choice kept; the latest holds."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def put(self, choice: RoleChoice) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.model_role_choices (role_id, body) VALUES (%s, %s)",
                (choice.role_id, json.dumps(choice.model_dump())),
            )

    def latest(self, role_id: str) -> RoleChoice | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT body FROM domain.model_role_choices WHERE role_id = %s"
                " ORDER BY seq DESC LIMIT 1",
                (role_id,),
            ).fetchone()
        return RoleChoice.model_validate(row[0], strict=False) if row else None


@dataclass
class Router:
    """What the senders ask: the pin for a role now, and what to do on a policy refusal."""

    policies: Any = field(default_factory=InMemoryPolicyStore)
    choices: Any = field(default_factory=InMemoryRoleChoiceStore)
    http: Any = None  # httpx.Client (tests)

    def pick(self, role: Any) -> Pick:
        return pick(role, self.policies, self.choices.latest(role.role_id))

    def refresh(self) -> int:
        """Read the policies now; the number of providers read (0 when it failed)."""
        try:
            rows = fetch(self.http)
        except Exception:
            log.exception("provider policies not read")
            return 0
        self.policies.put_all(rows)
        return len(rows)

    def refused(self, message: str) -> bool:
        """After an OpenRouter answer: a data-policy refusal reads the policies again (True)."""
        if DATA_POLICY_REFUSAL not in message.lower():
            return False
        return self.refresh() > 0
