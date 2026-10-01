"""WP-00: the fake SagaEye satisfies the protocol and returns empty witness data."""

from __future__ import annotations

from poarta_contabila.sinks.saga_eye import FakeSagaEye, SagaEye


def test_fake_saga_eye_is_empty():
    eye: SagaEye = FakeSagaEye()
    assert eye.documents("1000009", "2026-09") == []
    assert eye.solduri("1000009", "2026-09") == {}
    assert eye.analytic("1000009", "2026-09", "401") == {}
    assert isinstance(eye, SagaEye)
