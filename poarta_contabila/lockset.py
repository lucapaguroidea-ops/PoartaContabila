"""core.provenance: the lock set a computed result was read under (R36 of the module review).

A result that cites the law or the practice is only as good as the pins it read: the core's
version, the notes library's register at a commit, the legal corpus at a release. When one of
them is corrected or revoked, the results that read the old pin must be found, not guessed.
So each result records its ``LockSet``, and ``impacted`` returns exactly the results of a pin.

Today the calendar's entries carry it. The legal corpus is not pinned in this repository yet:
its release is recorded as ``None`` (``unpinned``) rather than invented.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, TypeVar

from poarta_contabila.catalog import Catalog

_SHA = re.compile(r"[0-9a-f]{40}")
T = TypeVar("T")


class LockSetError(ValueError):
    """A pin the lock set cannot name exactly."""


@dataclass(frozen=True)
class LockSet:
    core: str  # CORE_VERSION
    library: str | None  # the notes library register's full commit
    corpus: str | None  # the legal corpus release; None until one is pinned

    @property
    def key(self) -> str:
        lib = f"library@{self.library[:7]}" if self.library else "library@unpinned"
        return f"core-v{self.core}|{lib}|corpus@{self.corpus or 'unpinned'}"


def lock_set(cat: Catalog) -> LockSet:
    """The pins *cat* reads now. A register named without its full commit is refused."""
    from poarta_contabila.core import CORE_VERSION  # the core re-exports this module

    register = (cat.docs.get("ArticoleTerms") or {}).get("register") or {}
    commit = register.get("commit")
    if commit is not None and not _SHA.fullmatch(str(commit)):
        raise LockSetError(f"the register's commit must be a full 40-character sha: {commit!r}")
    return LockSet(core=CORE_VERSION, library=commit, corpus=None)


def impacted(
    entries: Iterable[T],
    *,
    core: str | None = None,
    library: str | None = None,
    corpus: str | None = None,
) -> list[T]:
    """The entries whose lock set matches every pin given (in their order)."""
    want = {k: v for k, v in (("core", core), ("library", library), ("corpus", corpus)) if v}
    if not want:
        raise LockSetError("name at least one pin to look for")
    return [e for e in entries if all(getattr(_lock(e), k) == v for k, v in want.items())]


def _lock(entry: Any) -> LockSet:
    lock = entry.get("lock") if isinstance(entry, dict) else getattr(entry, "lock", None)
    if not isinstance(lock, LockSet):
        raise LockSetError(f"an entry without a lock set: {entry!r}")
    return lock


__all__ = ["LockSet", "LockSetError", "impacted", "lock_set"]
