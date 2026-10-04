"""which invoice a bank line settles — a proposal for the person, never a decision."""

from __future__ import annotations

from decimal import Decimal

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
    p = propose_settlement(_unbound(desc="Incasare", gross="100.00"), [_invoice()])
    assert p.candidates == [] and p.edit is None and "no open invoice" in p.reason


# ----- partial payments, part-paid invoices, one payment for several invoices -----


def test_a_partial_payment_is_proposed_when_the_text_names_the_invoice():
    p = propose_settlement(_unbound(gross="100.00"), [_invoice()])
    (c,) = p.candidates
    assert c.cover == "partial" and c.open_after == "82.11" and "amount" not in c.hits
    assert p.edit["maps"] == {"factura_numar": "FX-101", "factura_id": "job-iesire"}
    assert "partial payment on FX-101" in p.reason and "82.11 stays open" in p.reason


def test_more_than_the_invoice_is_never_a_partial_payment():
    assert propose_settlement(_unbound(gross="200.00"), [_invoice()]).candidates == []


def test_the_text_naming_an_invoice_beats_an_amount_alone():
    line = _unbound(desc="Incasare fact BX-21", gross="100.00")
    p = propose_settlement(line, [], [_book("BX-21", gross="300.00"), _book("Z-9", "100.00")])
    assert [c.factura_numar for c in p.candidates] == ["BX-21", "Z-9"]
    assert p.edit["maps"] == {"factura_numar": "BX-21"} and p.candidates[0].cover == "partial"


def test_what_other_lines_paid_leaves_the_rest_open():
    key = settle_key(PARTNER, "FX-101")
    rest = propose_settlement(
        _unbound(desc="Incasare", gross="82.11"), [_invoice()], paid={key: Decimal("100.00")}
    )
    assert rest.candidates[0].cover == "full" and rest.edit is not None
    done = propose_settlement(_unbound(), [_invoice()], paid={key: Decimal("182.11")})
    assert done.candidates == [] and done.edit is None


def test_one_payment_for_several_invoices_is_a_group_and_never_an_edit():
    line = _unbound(desc="Incasare CLIENT TEST fact BX-1 BX-2", gross="300.00")
    books = [
        _book("BX-1", gross="100.00"),
        _book("BX-2", gross="200.00"),
        _book("BX-3", gross="50.00", cui=OTHER),
        _book("BX-4", gross="250.00", cui=OTHER),  # adds up too, but another partner …
    ]
    p = propose_settlement(line, [], books)
    assert p.candidates == [] and p.edit is None
    first = p.groups[0]
    assert [c.factura_numar for c in first.invoices] == ["BX-1", "BX-2"]
    assert first.hits == ["number_in_text"] and first.total == "300.00"
    assert {g.partner_cui for g in p.groups} == {PARTNER, OTHER}  # … listed after
    assert "one payment for 2 invoices" in p.reason and "posts it in SAGA" in p.reason


def test_a_full_fit_leaves_no_groups():
    books = [_book("B-1", gross="182.11"), _book("B-2", "100.00"), _book("B-3", "82.11")]
    p = propose_settlement(_unbound(desc="Incasare"), [], books)
    assert [c.factura_numar for c in p.candidates] == ["B-1"] and p.groups == []


def test_an_invoice_and_a_group_that_fit_as_well_give_no_edit():
    line = _unbound(desc="Incasare fact BX-1 BX-7 BX-8", gross="100.00")
    books = [_book("BX-1", gross="150.00"), _book("BX-7", "60.00"), _book("BX-8", "40.00")]
    p = propose_settlement(line, [], books)
    assert p.candidates[0].cover == "partial" and p.groups
    assert p.edit is None and "several together" in p.reason
    alone = propose_settlement(_unbound(desc="Incasare fact BX-1", gross="100.00"), [], books)
    assert alone.groups and alone.edit["maps"] == {"factura_numar": "BX-1"}  # the text decides


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
