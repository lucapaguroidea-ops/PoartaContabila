"""Postgres domain store (00_LAW A1)."""

from __future__ import annotations

from importlib.resources import files


def schema_sql() -> str:
    """The idempotent DDL for schema ``domain``."""
    return files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")
