"""the synthetic smoke run drives the whole flow over HTTP and shows each role's place."""

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
    # dry: the approval question waits; its explanation is recorded, not sent
    assert steps["approval explanation"].outcome.startswith("none: recorded (dry run")
    assert steps["line 2 v3_approve"].outcome.startswith("job packaged")
    assert steps["decont_split"].outcome == "workings emit=False"
    assert steps["eu route"].outcome.startswith("set on 0 of ")
    assert steps["monthly_close 2026-09"].outcome.startswith("material=True; held (hold)")
    # the clean month — every document already in the books, nothing blocks
    assert steps["registru jurnal"].outcome == "covers ['2026-08', '2026-09']"
    assert steps["august invoice"].outcome == "job already_in_sink"
    assert steps["august statement"].outcome == "job already_in_sink; job already_in_sink"
    assert steps["monthly_close 2026-08"].outcome == "material=False; held (hold)"
    assert {
        "folder_triage.sniff",
        "folder_triage.decont_split",
        "ingest_source_doc.extract",
        "ingest_source_doc.v3_classify",
        "monthly_close.layer2",
    } <= set(report.calls)
    # every role has its model (owner, 2026-10-03): in dry mode each records what it would be
    # sent, and nothing is sent
    calls = [c for cs in report.calls.values() for c in cs]
    assert {c["status"] for c in calls} == {"recorded"}
    assert {c["model"] for c in calls if c["role_id"].startswith("jev_")} == {"typesafe/jev-1.13"}
    assert "dry run: recorded, not sent" in render(report)

    again = run(client)  # a second run answers nothing new
    steps = _steps(again)
    assert steps["invoice v3_approve"].outcome.startswith("nothing to answer: job packaged")
    assert steps["line 2 v3_approve"].outcome.startswith("nothing to answer")
    assert steps["monthly_close 2026-08"].outcome == "material=False; held (hold)"  # same lock
    assert again.ok


def test_a_month_changed_since_its_lock_is_reopened_then_closed():
    from poarta_contabila.smoke import CUI, STATEMENT

    client = _local_client()
    run(client)
    later = {  # another September statement: a new line, so the month's jobs change
        **STATEMENT,
        "meta": {**STATEMENT["meta"], "opening": "4290.00", "closing": "4390.00"},
        "tables": [
            {
                "headers": ["Data", "Descriere", "Referinta", "Debit", "Credit"],
                "rows": [["28.09.2026", "Incasare CLIENT TEST SRL FX-103", "", "", "100,00"]],
            }
        ],
        "pdf_b64": "JVBERi0xLjQgbGF0ZXI=",  # %PDF-1.4 later
    }
    assert client.post(f"/extras/{CUI}", json=later).status_code == 200
    steps = _steps(run(client))
    assert steps["monthly_close 2026-09"].outcome.startswith(
        "reopened after a lock mismatch; material=True; held (hold)"
    )
    assert "lock mismatch" not in steps["monthly_close 2026-09"].outcome.split("; ", 1)[1]
    assert steps["monthly_close 2026-08"].outcome == "material=False; held (hold)"


def test_the_smoke_run_refuses_a_server_that_would_send():
    with pytest.raises(SmokeRefused, match="needs off, dry or live"):
        run(_local_client(), allow_mode=lambda mode: False)


def test_the_command_needs_the_operator_token(monkeypatch, capsys):
    for name in ("GRAPHUSERTOKEN_OPERATOR", "GRAPHUSERTOKEN_CLAUDE_SYSBUILDER", "OPERATOR_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert main(["--base-url", "https://example.invalid"]) == 2
    assert "GRAPHUSERTOKEN_OPERATOR" in capsys.readouterr().out
    assert main(["--local"]) == 0
    assert "monthly_close" in capsys.readouterr().out


def test_the_invoice_is_the_same_bytes_on_every_run(monkeypatch):
    import time

    first = spv_invoice()
    real = time.localtime
    monkeypatch.setattr(time, "localtime", lambda *a: real(time.time() + 3600))
    assert spv_invoice() == first  # a rerun later finds the same Job, never a duplicate


def test_the_ocr_step_has_the_server_read_a_synthetic_statement_pdf():
    import dataclasses
    import json

    import httpx

    from poarta_contabila.catalog import load_catalog
    from poarta_contabila.extract.gemini import GeminiStatementReader
    from poarta_contabila.smoke import synthetic_statement_pdf
    from tests.test_runtime import _runtime

    cat = load_catalog()
    roles = dict(cat.model_roles)
    roles["ocr_extract"] = roles["ocr_extract"].model_copy(update={"model": "gemini-test-001"})
    rt = _runtime(dataclasses.replace(cat, model_roles=roles), model_mode="live")
    answer = {
        "header": {
            "iban": "RO49 AAAA 1B31 0075 9384 0000",
            "holder_cui": "RO1000009",
            "currency": "RON",
            "opening": "4.290,00",
            "closing": "4.590,00",
            "statement_date": "30.09.2026",
        },
        "tables": [
            {
                "headers": ["Data", "Descriere", "Referinta", "Debit", "Credit"],
                "rows": [
                    ["25.09.2026", "Incasare CLIENT TEST SRL FX-102", "OP-91", "", "300,00"],
                    ["", "Total rulaje", "", "0,00", "300,00"],
                ],
            }
        ],
    }
    sent = []

    def google(request):
        sent.append(request)
        text = json.dumps(answer)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    rt.gemini_reader = GeminiStatementReader(
        role=roles["ocr_extract"],
        key="k",
        calls=rt.model_calls,
        synthetic=rt._synthetic,
        http=httpx.Client(transport=httpx.MockTransport(google)),
    )
    report = run(_local_client(rt), ocr=True)
    step = _steps(report)["statement PDF read"]
    assert step.ok and step.outcome.startswith("job reconcile_pre asks v3_approve")
    assert len(sent) == 1 and b"FX-102" in synthetic_statement_pdf()
    # the statements sent with their tables (September, and August) record what Gemini
    # would be given; this one was sent
    statuses = [c["status"] for c in report.calls["ingest_source_doc.extract"]]
    assert sorted(statuses) == ["recorded", "recorded", "sent"]
    run(_local_client(rt), ocr=True)  # a rerun: the stored extract, no second call
    assert len(sent) == 1
