"""SagaEye: the read-only witness protocol (ARCHITECTURE.md §6).

Core graphs depend only on this protocol. v1 reads the SAGA report pack /
RJ-CM export (WP-07); FDB SQL is parked (WP-15).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from poarta_contabila.types import SinkDoc


@runtime_checkable
class SagaEye(Protocol):
    def covers(self, cui: str, period: str) -> bool:
        """True only if this witness holds the firm's books for that month.

        "Not in the books" may be concluded only for a covered month (PRE ``absent``).
        """
        ...

    def documents(self, cui: str, period: str) -> list[SinkDoc]: ...

    def solduri(self, cui: str, period: str) -> dict[str, dict]: ...

    def analytic(self, cui: str, period: str, root: str) -> dict[str, dict]: ...


class FakeSagaEye:
    """Witness with nothing in it. For tests and for graphs before WP-07."""

    def covers(self, cui: str, period: str) -> bool:
        return False

    def documents(self, cui: str, period: str) -> list[SinkDoc]:
        return []

    def solduri(self, cui: str, period: str) -> dict[str, dict]:
        return {}

    def analytic(self, cui: str, period: str, root: str) -> dict[str, dict]:
        return {}
