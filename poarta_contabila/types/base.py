"""Shared scalar types and the closed base model.

Money and fiscal dates travel as strings (LAW L24). Decimals are
built only inside compute nodes, from these strings.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

_CUI_KEY = "753217532"


def cui_is_valid(value: str) -> bool:
    """True if *value* is a CUI/CIF key: 2-10 digits, no ``RO``, valid check digit."""
    if not (isinstance(value, str) and value.isdigit() and 2 <= len(value) <= 10):
        return False
    body, check = value[:-1].zfill(9), int(value[-1])
    total = sum(int(d) * int(k) for d, k in zip(body, _CUI_KEY, strict=True))
    expected = total * 10 % 11
    return (0 if expected == 10 else expected) == check


def cui_key(raw: str | None) -> str | None:
    """A printed fiscal code (``RO 123``, ``ro123``, ``123``) → the CUI key, or None if invalid."""
    if not raw:
        return None
    digits = raw.replace(" ", "").upper().removeprefix("RO")
    return digits if cui_is_valid(digits) else None


def _check_cui(value: str) -> str:
    if not cui_is_valid(value):
        raise ValueError("CUI must be 2-10 digits without RO prefix and with a valid check digit")
    return value


Money = Annotated[str, StringConstraints(pattern=r"^-?\d+\.\d{2}$")]
"""Amount as a string with exactly two decimals, e.g. ``"1234.67"``."""

Rate = Annotated[str, StringConstraints(pattern=r"^\d+(\.\d{1,4})?$")]
"""Percentage or FX rate as a string, e.g. ``"21"`` or ``"4.9750"``."""

FiscalDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
"""ISO date string, e.g. ``"2026-09-15"``."""

Period = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
"""Firm-month, ``YYYY-MM``."""

Cui = Annotated[str, AfterValidator(_check_cui)]
"""Tenant or partner fiscal code used as a key: digits only, check digit verified."""

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.-]*$")]


class Closed(BaseModel):
    """Base for every domain type: unknown keys are refused, values are not coerced."""

    model_config = ConfigDict(extra="forbid", strict=True)
