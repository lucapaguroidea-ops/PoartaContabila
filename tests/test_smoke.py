"""WP-29: the synthetic smoke run drives the whole flow over HTTP and shows each role's place."""

from __future__ import annotations

import pytest

from poarta_contabila.smoke import SmokeRefused, _local_client, main, render, run, spv_invoice


def _steps(report):
    return {s.name: s for s in report.steps}


def test_the_smoke_run_goes_through_every_graph():
    client = _local_client()
    report = run(client)
    assert report.ok and report.mode == "dry"
    steps = _steps(report)
    assert steps["invoice v3_approve"].outcome.startswith("job packaged")
    assert steps["line 2 v3_approve"].outcome.startswith("job packaged")
    assert steps["decont_split"].outcome == "workings emit=False"
    assert steps["eu route"].outcome.startswith("set on 0 of ")
    assert steps["monthly_close"].outcome.startswith("material=True; held (hold)")
    assert {
        "folder_triage.sniff",
        "folder_triage.decont_split",
        "ingest_source_doc.extract",
        "ingest_source_doc.v3_classify",
        "monthly_close.layer2",
    } <= set(report.calls)
    # no model ids yet: every role refuses, and says why
    calls = [c for cs in report.calls.values() for c in cs]
    assert {c["status"] for c in calls} == {"refused"}
    assert "no model chosen" in render(report)

    again = run(client)  # a second run answers nothing new
    steps = _steps(again)
    assert steps["invoice v3_approve"].outcome.startswith("nothing to answer: job packaged")
    assert steps["line 2 v3_approve"].outcome.startswith("nothing to answer")
    assert again.ok


def test_the_smoke_run_refuses_a_server_that_would_send():
    with pytest.raises(SmokeRefused, match="needs off or dry"):
        run(_local_client(), allow_mode=lambda mode: False)


def test_the_command_needs_the_operator_token(monkeypatch, capsys):
    monkeypatch.delenv("OPERATOR_TOKEN", raising=False)
    assert main(["--base-url", "https://example.invalid"]) == 2
    assert "OPERATOR_TOKEN" in capsys.readouterr().out
    assert main(["--local"]) == 0
    assert "monthly_close" in capsys.readouterr().out


def test_the_invoice_is_the_same_bytes_on_every_run(monkeypatch):
    import time

    first = spv_invoice()
    real = time.localtime
    monkeypatch.setattr(time, "localtime", lambda *a: real(time.time() + 3600))
    assert spv_invoice() == first  # a rerun later finds the same Job, never a duplicate
