"""WP-22: which invoice a bank line settles — a proposal for the person, never a decision."""

from __future__ import annotations

import pytest

from poarta_contabila.recon.settle import (
    InvoiceJob,
    name_in_text,
    number_in_text,
    propose_settlement,
    settle_key,
)
from poarta_contabila.sinks.saga_xml import bank_fixture_documents, fixture_documents
from poarta_contabila.types import PartnerRef, SinkDoc

PARTNER = "20000005"  # invented, valid check digit
OTHER = "30000002"  # invented, valid check digit


def _unbound(kind="incasare", desc="Incasare CLIENT TEST SRL FX-101", gross="182.11"):
    doc = bank_fixture_documents()[kind]
    line = doc.lines[0].model_copy(update={"desc": desc, "net": gross, "gross": gross})
    return doc.model_copy(
        update={
            "partner": PartnerRef(cui=None, name=desc, role="unknown"),
            "maps": {"iban": doc.maps["iban"], "statement_id": "0f0f0f0f"},
            "lines": [line],
            "totals": doc.totals.model_copy(update={"net": gross, "gross": gross}),
        }
    )


def _invoice(kind="iesire", **update):
    return InvoiceJob(job_id=f"job-{kind}", doc=fixture_documents()[kind].model_copy(update=update))


def _book(number, gross="182.11", cui=PARTNER, doc_class="iesire", date="2026-09-12"):
    return SinkDoc(
        saga_key=f"saga-{number}",
        doc_class=doc_class,
        number=number,
        date=date,
        partner_cui=cui,
        gross=gross,
        net=gross,
        vat="0.00",
        validated=True,
    )


@pytest.mark.parametrize(
    ("number", "text", "hit"),
    [
        ("FX-101", "Incasare CLIENT TEST SRL FX-101", True),
        ("FX-101", "incasare fx 101 client", True),
        ("FX101", "plata FX-101", True),
        ("1427", "Plata FURNIZOR TEST SRL fact 1427", True),
        ("1427", "Plata 14270 lei", False),
        ("12", "Plata fact 12", False),  # too short to tell
        ("A-77", "Plata A-770", False),
    ],
)
def test_number_reads_in_text_as_whole_tokens(number, text, hit):
    assert number_in_text(number, text) is hit


def test_name_reads_without_legal_forms():
    assert name_in_text("Client Test SRL", "INCASARE CLIENT TEST")
    assert name_in_text("S.C. Client Test S.R.L.", "op client test srl")
    assert not name_in_text("Client Test SRL", "incasare client")
    assert not name_in_text("SRL", "srl")  # nothing telling left


def test_one_invoice_with_amount_and_number_gives_a_ready_edit():
    p = propose_settlement(_unbound(), [_invoice(), _invoice("intrare")])
    assert [c.factura_numar for c in p.candidates] == ["FX-101"]  # the purchase is the other side
    assert p.candidates[0].hits == ["amount", "number_in_text", "name_in_text"]
    assert p.edit == {
        "partner": {"cui": PARTNER, "name": "Client Test SRL", "role": "customer"},
        "maps": {"factura_numar": "FX-101", "factura_id": "job-iesire"},
    }


def test_a_payment_settles_a_purchase():
    line = _unbound("plata", desc="Plata FURNIZOR TEST fact A-77", gross="242.00")
    p = propose_settlement(line, [_invoice(), _invoice("intrare")])
    assert p.edit["partner"]["role"] == "supplier"
    assert p.edit["maps"] == {"factura_numar": "A-77", "factura_id": "job-intrare"}


@pytest.mark.parametrize(
    ("update", "why"),
    [
        ({"date": "2026-09-21"}, "issued after the line"),
        ({"is_storno": True, "storno_of": "x"}, "storno"),
    ],
)
def test_an_invoice_that_cannot_be_settled_is_no_candidate(update, why):
    assert propose_settlement(_unbound(), [_invoice(**update)]).candidates == [], why


def test_another_amount_is_no_candidate():
    p = propose_settlement(_unbound(gross="100.00"), [_invoice()])
    assert p.candidates == [] and p.edit is None and "no open invoice" in p.reason


def test_an_invoice_another_line_names_is_no_candidate():
    assert (
        propose_settlement(
            _unbound(), [_invoice()], settled_ids=frozenset({"job-iesire"})
        ).candidates
        == []
    )
    by_number = frozenset({settle_key(PARTNER, "fx 101")})
    assert propose_settlement(_unbound(), [_invoice()], settled_numbers=by_number).candidates == []


def test_two_equal_fits_give_a_list_and_no_edit():
    line = _unbound(desc="Incasare 182,11")  # neither number nor name in the text
    books = [_book("B-1"), _book("B-2", cui=OTHER)]
    p = propose_settlement(line, [], books)
    assert {c.factura_numar for c in p.candidates} == {"B-1", "B-2"}
    assert p.edit is None and "2 invoices fit equally" in p.reason


def test_the_text_breaks_a_tie():
    line = _unbound(desc="Incasare fact BX-22")
    p = propose_settlement(line, [], [_book("BX-21"), _book("BX-22", cui=OTHER)])
    assert p.edit["partner"]["cui"] == OTHER
    assert p.edit["maps"] == {"factura_numar": "BX-22"}  # from the books: no FacturaID


def test_a_job_and_the_books_showing_one_invoice_are_one_candidate():
    p = propose_settlement(_unbound(), [_invoice()], [_book("FX-101")])
    assert len(p.candidates) == 1 and p.candidates[0].source == "job"


def test_an_amount_alone_is_proposed_but_says_so():
    p = propose_settlement(_unbound(desc="Incasare"), [_invoice()])
    assert p.edit is not None and "the amount alone" in p.reason


def test_only_an_unbound_bank_line_carries_a_proposal():
    from poarta_contabila.ingest import _proposal

    class Deps:
        calls = 0

        def settlement(self, doc):
            Deps.calls += 1
            return propose_settlement(doc, [_invoice()])

    deps = Deps()
    assert "proposal" in _proposal(deps, _unbound())
    bound = _unbound().model_copy(
        update={"partner": PartnerRef(cui=PARTNER, name="X", role="customer")}
    )
    assert _proposal(deps, bound) == {}
    assert _proposal(deps, fixture_documents()["iesire"]) == {}  # not a bank line
    assert Deps.calls == 1

    class Broken:
        def settlement(self, doc):
            raise RuntimeError("books unreadable")

    assert _proposal(Broken(), _unbound()) == {}  # the question is still asked
