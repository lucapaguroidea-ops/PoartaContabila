"""WP-37: the reading evaluation — known statements, scored readings, any AI Studio model."""

from __future__ import annotations

import base64
import copy
import dataclasses
import json

import httpx
import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.extract.gemini import GeminiStatementReader
from poarta_contabila.ocr_eval import cases, lenient_lines, main, render, score, summary
from tests.test_runtime import CUI, Ops, _runtime


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _reader(cat, answer_for, *, model="gemini-3.8-flash", synthetic=lambda cui: True):
    """A reader whose stand-in Google answers each case with ``answer_for(case)``."""
    by_pdf = {base64.b64encode(c.pdf()).decode(): c for c in cases()}

    def google(request):
        body = json.loads(request.content)
        case = by_pdf[body["contents"][0]["parts"][0]["inlineData"]["data"]]
        text = json.dumps(answer_for(case))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    role = cat.model_roles["ocr_extract"].model_copy(update={"model": model})
    from poarta_contabila.model_roles import InMemoryModelCallStore

    return GeminiStatementReader(
        role=role,
        key="k",
        calls=InMemoryModelCallStore(),
        synthetic=synthetic,
        http=httpx.Client(transport=httpx.MockTransport(google)),
    )


def test_the_cases_are_deterministic_and_vary_what_statements_vary():
    a, b = cases(), cases()
    assert [c.pdf() for c in a] == [c.pdf() for c in b]
    assert {c.name for c in a} == {
        "simple",
        "ro_labels",
        "continuation",
        "column_order",
        "two_pages",
        "dense",
    }
    two = next(c for c in a if c.name == "two_pages")
    assert len(two.pages) == 2 and len(two.answer["tables"]) == 2
    assert all(c.pdf().startswith(b"%PDF-1.4") for c in a)


def test_a_perfect_reading_scores_full_marks_on_every_case(cat):
    scores = [score(c, _reader(cat, lambda case: case.answer)) for c in cases()]
    assert all(s.read and s.ties and s.identity and s.iban for s in scores), render(scores)
    assert all(s.lines_exact == s.lines_expected and s.header_fields == 6 for s in scores)
    total = summary(scores)
    assert total["lines_exact"] == total["lines_expected"] == 2 + 6 + 9 + 8 + 60 + 30


def test_a_dropped_line_breaks_the_tie_and_costs_lines(cat):
    def drop_one(case):
        answer = copy.deepcopy(case.answer)
        del answer["tables"][0]["rows"][0]
        return answer

    s = score(cases()[0], _reader(cat, drop_one))
    assert s.read and not s.ties and s.lines_exact == 0 and s.lines_expected == 2


def test_a_misread_header_field_is_counted(cat):
    def wrong_closing(case):
        answer = copy.deepcopy(case.answer)
        answer["header"]["closing"] = "1,00"
        return answer

    s = score(cases()[0], _reader(cat, wrong_closing))
    assert s.header_fields == 5 and s.ties  # the person's typed header still ties the lines


def test_a_refused_reading_is_a_score_not_a_crash(cat):
    s = score(cases()[0], _reader(cat, lambda case: case.answer, synthetic=lambda cui: False))
    assert not s.read and "client data never goes" in s.error


def test_lenient_lines_skip_what_does_not_read():
    tables = [
        {
            "headers": ["Data", "Descriere", "Debit", "Credit"],
            "rows": [
                ["01.09.2026", "Plata", "10,00", ""],
                ["", "continuare", "", ""],
                ["02.09.2026", "?", "x", ""],
                ["03.09.2026", "Total rulaje", "10,00", "0,00"],
            ],
        }
    ]
    assert [line[:2] for line in lenient_lines(tables)] == [("2026-09-01", "debit")]


# ----- over HTTP -----


def _ops(cat, reader, data_class="synthetic"):
    rt = _runtime(cat)
    o = Ops(rt)
    body = {"cui": CUI, "name": "F", "saga_firm_folder": "0001", "data_class": data_class}
    o.http.put(f"/tenants/{CUI}", json=body, headers=o.op)
    rt.gemini_reader = reader
    if reader is not None:
        reader.calls, reader.synthetic = rt.model_calls, rt._synthetic
    return o


def test_the_endpoint_scores_a_case_with_the_pinned_or_another_model(cat):
    o = _ops(cat, _reader(cat, lambda case: case.answer))
    out = o.http.post(f"/ocr-eval/{CUI}", params={"case": "simple"}, headers=o.op).json()
    (s,) = out["scores"]
    assert s["case"] == "simple" and s["ties"] and s["model"] == "gemini-3.8-flash"
    pro = o.http.post(
        f"/ocr-eval/{CUI}", params={"case": "simple", "model": "gemini-3.1-pro"}, headers=o.op
    ).json()
    assert pro["scores"][0]["model"] == "gemini-3.1-pro"
    calls = o.http.get("/model-calls", params={"role": "ocr_extract"}, headers=o.op).json()
    assert sorted(c["model"] for c in calls) == ["gemini-3.1-pro", "gemini-3.8-flash"]
    assert o.rt.jobs.jobs == {}  # nothing minted


@pytest.mark.parametrize(
    ("params", "data_class", "wired", "match"),
    [
        ({}, "client", True, "not a registered synthetic tenant"),
        ({}, "synthetic", False, "not wired"),
        ({"model": "google/gemini-3.1-pro"}, "synthetic", True, "not a Google AI Studio"),
        ({"model": "gemini-pro-latest"}, "synthetic", True, "not a Google AI Studio"),
        ({"case": "nope"}, "synthetic", True, "unknown case"),
    ],
)
def test_the_endpoint_refuses(cat, params, data_class, wired, match):
    reader = _reader(cat, lambda case: case.answer) if wired else None
    o = _ops(cat, reader, data_class)
    resp = o.http.post(f"/ocr-eval/{CUI}", params=params, headers=o.op)
    assert resp.status_code == 422 and match in resp.json()["detail"]


def test_the_command_writes_the_pdfs_to_look_at(tmp_path, capsys):
    assert main(["--write-pdfs", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(f"{c.name}.pdf" for c in cases())
    assert "two movements" in capsys.readouterr().out


def test_the_command_needs_the_operator_token(monkeypatch, capsys):
    monkeypatch.delenv("OPERATOR_TOKEN", raising=False)
    assert main(["--base-url", "https://example.invalid"]) == 2


def test_the_reader_override_keeps_every_guard(cat):
    reader = _reader(cat, lambda case: case.answer, synthetic=lambda cui: False)
    other = dataclasses.replace(reader, role=reader.role.model_copy(update={"model": "gemini-x"}))
    assert not score(cases()[0], other).read  # a client tenant is refused whatever the model
