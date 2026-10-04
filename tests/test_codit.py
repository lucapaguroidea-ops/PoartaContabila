"""CO.DiT — period tax profile; hard pairs refuse, soft pairs flag, empty is not a payer."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from poarta_contabila.catalog import load_catalog
from poarta_contabila.close import close_kind
from poarta_contabila.codit import (
    AxisValue,
    CoditError,
    CoditInput,
    InMemoryCoditStore,
    write_codit,
)
from tests.test_controls import CUI, PERIOD


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def A(value, certainty="confirmed"):  # noqa: N802
    return AxisValue(value=value, certainty=certainty, as_of="2026-09-01", source="test")


def _w(cat, previous=None, closed=False, **axes):
    extra = {k: axes.pop(k) for k in ("parent_cui", "saf_t", "vehicle_count", "auto") if k in axes}
    data = CoditInput(
        axes={k: A(v) if not isinstance(v, AxisValue) else v for k, v in axes.items()}, **extra
    )
    return write_codit(cat, CUI, PERIOD, data, previous=previous, closed=closed)


def test_empty_profile_is_not_a_payer(cat):
    doc = _w(cat)
    assert doc.derive() == {} and "tva" not in doc.axes
    assert close_kind(cat, doc.derive()) is None  # nothing can be closed on a guess


def test_neplatitor_with_vat_on_collection_is_refused(cat):
    with pytest.raises(CoditError, match="T1 exig_requires_platitor"):
        _w(cat, tva="tva_neplatitor", exig="tva_la_incasare")


def test_t2_exig_set_on_a_small_business_exemption(cat):
    with pytest.raises(CoditError, match="T2"):
        _w(cat, tva="tva_scutire_mici", exig="tva_exig_livrare")


def test_t3_payer_with_exig_explicitly_empty(cat):
    with pytest.raises(CoditError, match="T3"):
        _w(cat, tva="tva_platitor", exig=None)


def test_defaults_fill_only_an_omitted_exig(cat):
    payer = _w(cat, tva="tva_platitor")
    assert payer.derive()["exig"] == "tva_exig_livrare"
    assert payer.axes["exig"].source == "default from tva"
    non = _w(cat, tva="tva_neplatitor")
    assert "exig" not in non.derive()
    incasare = _w(cat, tva="tva_platitor", exig="tva_la_incasare")
    assert close_kind(cat, incasare.derive()) == "close_tva_incasare"


@pytest.mark.parametrize(
    ("axes", "pair"),
    [
        ({"forma": "sucursala", "impozit": "micro_1"}, "F5"),  # before F3
        ({"forma": "prof", "impozit": "micro_1"}, "F6"),
        ({"forma": "srl", "impozit": "pfa_norma"}, "F1"),
        ({"forma": "srl", "impozit": "ong_scutit"}, "F2"),
        ({"forma": "pfa", "impozit": "profit_16"}, "F4"),
        ({"forma": "ong", "impozit": "micro_1"}, "F3"),
    ],
)
def test_form_and_tax_hard_pairs(cat, axes, pair):
    with pytest.raises(CoditError, match=f"^{pair} "):
        _w(cat, **axes)


def test_soft_pairs_are_flags_and_some_block_filing(cat):
    doc = _w(cat, forma="ong", impozit="profit_16", tva="tva_platitor")
    codes = {f.pair_id: f for f in doc.soft}
    assert codes["F7.1"].blocks_file and codes["F7.6"].hitl == "codit_combo"
    assert doc.blocks_file == ["F7.1 ong_economic"]
    branch = _w(cat, forma="sucursala", tva="tva_platitor")
    assert "F7.3" in {f.pair_id for f in branch.soft}  # parent CUI missing
    with_parent = _w(cat, forma="sucursala", tva="tva_platitor", parent_cui="20000005")
    assert "F7.3" not in {f.pair_id for f in with_parent.soft}


def test_every_axis_needs_certainty_and_a_known_value(cat):
    with pytest.raises(ValidationError):
        CoditInput.model_validate({"axes": {"tva": {"value": "tva_platitor"}}})
    with pytest.raises(ValueError, match="not one of"):
        _w(cat, tva="tva_mostly")
    with pytest.raises(ValueError, match="unknown CO.DiT axis"):
        _w(cat, mood="good")


def test_contested_and_flipped_premises_are_flagged(cat):
    first = _w(cat, tva="tva_platitor", employees=A("has", "contested"))
    assert "A_CONTESTED" in {f.pair_id for f in first.soft}
    second = _w(cat, previous=first, tva="tva_neplatitor")
    flip = next(f for f in second.soft if f.pair_id == "A_FLIP")
    assert flip.code == "flip:tva" and flip.hitl == "codit_premise"
    assert second.axes["employees"].value == "has"  # untouched axes are kept


def test_pins_are_copied_at_seed_and_kept(cat):
    doc = _w(cat, tva="tva_platitor")
    assert doc.pins["pins_id"] == "pins_ro_2026"
    assert doc.pins["provenance"]["certainty"] == "de_confirmat"
    later = _w(
        cat,
        previous=doc.model_copy(update={"pins": {"pins_id": "frozen"}}),
        impozit="micro_1",
        forma="srl",
    )
    assert later.pins == {"pins_id": "frozen"}  # a period's pins are never re-read


def test_same_profile_same_hash(cat):
    assert _w(cat, tva="tva_platitor").hash == _w(cat, tva="tva_platitor").hash


# ----- runtime -----


def test_codit_drives_the_period_and_the_close(cat):
    from tests.test_runtime import Ops, _runtime

    o = Ops(_runtime(cat, codits=InMemoryCoditStore()))
    o.tenant()
    o.upload_rj()
    assert o.http.get(f"/codit/{CUI}/{PERIOD}", headers=o.op).status_code == 404
    bad = o.http.put(
        f"/codit/{CUI}/{PERIOD}",
        headers=o.op,
        json={
            "axes": {
                "tva": {"value": "tva_neplatitor", "certainty": "confirmed"},
                "exig": {"value": "tva_la_incasare", "certainty": "confirmed"},
            }
        },
    )
    assert bad.status_code == 422 and "T1" in bad.json()["detail"]
    assert o.http.get(f"/codit/{CUI}/{PERIOD}", headers=o.op).status_code == 404  # not saved
    ok = o.http.put(
        f"/codit/{CUI}/{PERIOD}",
        headers=o.op,
        json={
            "axes": {
                "tva": {"value": "tva_platitor", "certainty": "confirmed"},
                "forma": {"value": "ong", "certainty": "confirmed"},
                "impozit": {"value": "profit_16", "certainty": "de_confirmat"},
            }
        },
    ).json()
    assert ok["axes"]["exig"]["value"] == "tva_exig_livrare"
    diff = o.http.get(f"/periods/{CUI}/{PERIOD}/diff", headers=o.op).json()
    statuses = {c["control_id"]: c["status"] for c in diff["controls"]}
    assert statuses["T_regime_4428"] == "PASS"  # the regime now comes from CO.DiT
    close = o.http.post(f"/close/{CUI}/{PERIOD}", headers=o.op).json()
    assert close["run"]["close_kind"] == "close_standard"
    assert any("F7.1" in b for b in close["question"]["blockers"])  # soft pair blocks filing


def test_postgres_codit_store(cat):
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    from poarta_contabila.codit import PostgresCoditStore
    from poarta_contabila.jobs import PostgresJobStore

    PostgresJobStore(dsn, reset=True)
    store = PostgresCoditStore(dsn)
    doc = _w(cat, tva="tva_platitor")
    store.put(doc)
    store.put(_w(cat, previous=doc, impozit="micro_1", forma="srl"))
    back = store.get(CUI, PERIOD)
    assert back.derive()["impozit"] == "micro_1" and back.derive()["tva"] == "tva_platitor"


def test_a_written_exig_is_never_wiped_by_a_tva_change(cat):
    defaulted = _w(cat, tva="tva_platitor")
    assert "exig" not in _w(cat, previous=defaulted, tva="tva_neplatitor").derive()
    written = _w(cat, tva="tva_platitor", exig="tva_exig_livrare")
    with pytest.raises(CoditError, match="T2"):
        _w(cat, previous=written, tva="tva_neplatitor")
