"""Invoice numbers for matching (LAW L18, ``[de confirmat]``).

SAGA's "Nr. doc" holds either the bare number or series and number; NextUp keeps what
was typed. Three levels, strongest first:

- ``exact``: trimmed, upper-case;
- ``alnum``: letters and digits only (``AB 0058`` = ``ab-0058`` = ``AB0058``);
- ``digits_core``: the digits without leading zeros (``AB0058`` = ``58``). Weak: many
  invoices share it, so the matcher counts it only with the same partner CUI.

The levels a profile accepts are its ``number_match`` list (ARTICOLE_RECONCILE).
"""

from __future__ import annotations

from typing import Literal

NumberLevel = Literal["exact", "alnum", "digits_core"]
LEVELS: tuple[NumberLevel, ...] = ("exact", "alnum", "digits_core")


def normalize(raw: str | None, level: NumberLevel) -> str | None:
    """The number at one level, or None when nothing is left to compare."""
    text = (raw or "").strip().upper()
    if level == "exact":
        return text or None
    if level == "alnum":
        return "".join(ch for ch in text if ch.isalnum()) or None
    if level == "digits_core":
        return "".join(ch for ch in text if ch.isdigit()).lstrip("0") or None
    raise ValueError(f"unknown number level {level!r}")


def match_level(
    a: str | None, b: str | None, levels: tuple[NumberLevel, ...]
) -> NumberLevel | None:
    """The strongest accepted level at which two numbers agree, or None."""
    for level in LEVELS:
        if level in levels:
            x = normalize(a, level)
            if x is not None and x == normalize(b, level):
                return level
    return None
