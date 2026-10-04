"""What each OpenRouter key has spent, read from OpenRouter: never computed here.

- **The service's keys** (each OpenRouter ``key_env`` of the catalog: ``OPENROUTER_SYS1_API_KEY``,
  ``OPENROUTER_SYS2_API_KEY``): ``GET https://openrouter.ai/api/v1/key`` with that key gives its
  spend (all time, today, this week, this month), its credit limit, what is left of it and when
  the limit resets. OpenRouter's ``label`` for the key is not passed on: it can show part of
  the key.
- **The whole account**, only when ``OPENROUTER_MANAGEMENT_KEY`` is set: ``GET /api/v1/credits``
  (credits bought, credits used) and ``GET /api/v1/keys`` (every key of the account by name:
  spend, limit, what is left, disabled). Read only: nothing here creates, changes or deletes a
  key, and a management key cannot make model calls.

Amounts are OpenRouter credits (US dollars), as OpenRouter reports them. A key value never
leaves this module: not in the answer, not in a log line.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

KEY_URL = "https://openrouter.ai/api/v1/key"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"
KEYS_URL = "https://openrouter.ai/api/v1/keys"
MANAGEMENT_ENV = "OPENROUTER_MANAGEMENT_KEY"
TIMEOUT_S = 20.0

KEY_FIELDS = (
    "usage",
    "usage_daily",
    "usage_weekly",
    "usage_monthly",
    "limit",
    "limit_remaining",
    "limit_reset",
    "is_free_tier",
)
ACCOUNT_KEY_FIELDS = (
    "name",
    "disabled",
    "usage",
    "usage_daily",
    "usage_weekly",
    "usage_monthly",
    "limit",
    "limit_remaining",
    "limit_reset",
    "created_at",
)


def _get(client: Any, url: str, secret: str) -> tuple[Any, str | None]:
    """(the JSON, None) or (None, why not)."""
    import httpx

    try:
        resp = client.get(url, headers={"Authorization": f"Bearer {secret}"})
    except httpx.HTTPError as exc:
        return None, f"OpenRouter unreachable: {type(exc).__name__}"
    if resp.status_code != 200:
        try:
            err = (resp.json() or {}).get("error") or {}
        except (ValueError, AttributeError):
            err = {}
        msg = str(err.get("message", "") if isinstance(err, dict) else "")[:200]
        return None, f"OpenRouter answered HTTP {resp.status_code}: {msg}".rstrip(": ")
    try:
        return resp.json(), None
    except ValueError:
        return None, "OpenRouter answered without JSON"


def key_usage(
    roles: dict[str, Any],
    *,
    http: Any = None,
    key: Callable[[str], str | None] = os.environ.get,
) -> dict[str, Any]:
    """Spend per OpenRouter key the catalog uses, and the account's when a management key is
    set (see the module docstring). *http*: an ``httpx.Client`` (tests); *key*: env lookup."""
    import httpx

    envs: dict[str, list[str]] = {}
    for role in roles.values():
        if role.route == "openrouter":
            envs.setdefault(role.key_env, []).append(role.role_id)
    client = http if http is not None else httpx.Client(timeout=TIMEOUT_S)
    try:
        keys = []
        for env, role_ids in sorted(envs.items()):
            row: dict[str, Any] = {"key_env": env, "roles": sorted(role_ids), "set": False}
            secret = key(env)
            if secret:
                row["set"] = True
                data, error = _get(client, KEY_URL, secret)
                if error:
                    row["error"] = error
                else:
                    found = (data or {}).get("data") or {}
                    row.update({name: found.get(name) for name in KEY_FIELDS})
            keys.append(row)
        return {
            "read_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "unit": "OpenRouter credits (USD)",
            "keys": keys,
            "account": _account(client, key(MANAGEMENT_ENV)),
        }
    finally:
        if http is None:
            client.close()


def _account(client: Any, secret: str | None) -> dict[str, Any] | None:
    if not secret:
        return None
    out: dict[str, Any] = {}
    data, error = _get(client, CREDITS_URL, secret)
    if error:
        out["credits_error"] = error
    else:
        found = (data or {}).get("data") or {}
        out["total_credits"] = found.get("total_credits")
        out["total_usage"] = found.get("total_usage")
    data, error = _get(client, KEYS_URL, secret)
    if error:
        out["keys_error"] = error
    else:
        rows = (data or {}).get("data") or []
        out["keys"] = [
            {name: row.get(name) for name in ACCOUNT_KEY_FIELDS}
            for row in rows
            if isinstance(row, dict)
        ]
    return out


def describe(view: dict[str, Any]) -> list[str]:
    """One line per key for the smoke report (amounts as OpenRouter gave them)."""

    def usd(value: Any) -> str:
        return "?" if value is None else f"${float(value):.4f}"

    lines = []
    for row in view.get("keys") or []:
        if not row.get("set"):
            text = "not set"
        elif row.get("error"):
            text = row["error"]
        else:
            left = (
                "no limit"
                if row.get("limit") is None
                else f"{usd(row.get('limit_remaining'))} left of {usd(row.get('limit'))}"
                + (f" ({row['limit_reset']})" if row.get("limit_reset") else "")
            )
            text = (
                f"spent {usd(row.get('usage_daily'))} today, {usd(row.get('usage'))} in all; {left}"
            )
        lines.append(f"{row['key_env']}: {text}")
    account = view.get("account")
    if account and "total_credits" in account:
        lines.append(
            f"account: {usd(account.get('total_usage'))} used of "
            f"{usd(account.get('total_credits'))} bought"
        )
    return lines
