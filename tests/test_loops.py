"""The loop kit (BUILD.md B6, item 2): files to a SAGA test firm, and its exports read back."""

from __future__ import annotations

import csv
import io
import shutil
from pathlib import Path

import pytest
import yaml

from poarta_contabila.loops import (
    KEYING_HEADER,
    LoopError,
    load_loop,
    main,
    prepare,
    read,
    simulated_exports,
)
from poarta_contabila.synthetic.firms import firm
from poarta_contabila.synthetic.months import month

FOLDER = "1001012-platitor"
TARGET = [
    "articol:ro_efactura_inbound",
    "articol:ro_efactura_outbound",
    "write_module:iesire_factura_xml",
]


def _loop(root: Path, **over) -> Path:
    d = root / "loop-01"
    d.mkdir(parents=True, exist_ok=True)
    body = {
        "loop": 1,
        "slice": "RO e-Factura, platitor",
        "status": "approved",
        "target_rows": TARGET,
        "exit": ["every target row is saga"],
        "runs": [{"firm": "platitor", "period": "2026-05"}],
        **over,
    }
    (d / "loop.yaml").write_text(yaml.safe_dump(body))
    return d


@pytest.fixture(scope="module")
def prepared(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("loops")
    _loop(root)
    prepare(1, root=root)
    return root


@pytest.fixture
def root(prepared, tmp_path) -> Path:
    """A fresh copy of the prepared loop, so each test may send back its own exports."""
    shutil.copytree(prepared, tmp_path / "loops")
    return tmp_path / "loops"


def _send_back(root: Path, files: dict[str, bytes] | None = None) -> Path:
    """The owner's exports: by default exactly what the generator expects SAGA to show."""
    out = root / "loop-01" / "exports" / FOLDER
    if files is None:
        shutil.copytree(root / "loop-01" / "prepared" / FOLDER / "simulated", out)
    else:
        out.mkdir(parents=True)
        for name, data in files.items():
            (out / name).write_bytes(data)
    return out


# ----- the loop file -----


def test_a_loop_must_be_approved_before_it_is_prepared(tmp_path):
    _loop(tmp_path, status="proposed")
    with pytest.raises(LoopError, match="approves the slice"):
        prepare(1, root=tmp_path)


def test_one_run_per_firm_and_the_number_matches(tmp_path):
    runs = [{"firm": "platitor", "period": "2026-05"}, {"firm": "platitor", "period": "2026-06"}]
    _loop(tmp_path, runs=runs)
    with pytest.raises(LoopError, match="one run per firm"):
        load_loop(1, tmp_path)
    _loop(tmp_path, loop=2)
    with pytest.raises(LoopError, match="loop 2, not 1"):
        load_loop(1, tmp_path)


# ----- prepare -----


def test_prepare_writes_what_the_owner_needs(prepared):
    out = prepared / "loop-01" / "prepared"
    base = out / FOLDER
    steps = (out / "STEPS.md").read_text()
    assert "Import date" in steps and "Nr.+data" in steps and "every target row is saga" in steps
    assert "not packaged" not in steps  # every package went to SAGA
    names = sorted(p.name for p in (base / "import").glob("run-*/*"))
    assert names and all(n.split("_")[0] in {"F", "I", "P"} for n in names)
    assert {p.name for p in (base / "simulated").iterdir()} == {
        "rj.xls",
        "balanta-2026-05.xlsx",
        "cumparari-2026-05.xls",
        "vanzari-2026-05.xls",
    }
    assert "`1001012`" in (base / "firm.md").read_text()


def test_the_keying_list_is_what_no_package_brings(prepared):
    rows = list(
        csv.reader(io.StringIO((prepared / "loop-01/prepared" / FOLDER / "keying.csv").read_text()))
    )
    assert rows[0] == KEYING_HEADER
    keyed = rows[1:]
    assert any(r[2] == "sold inițial" for r in keyed)  # the opening balances come first
    m = month(firm("platitor"), "2026-05")
    ours = {m.docs[r].number for r in ("p1", "p2", "p3", "s1", "s2")}
    assert not {r[3] for r in keyed} & ours  # no invoice we package is keyed by hand


# ----- read -----


def test_exports_as_the_generator_expects_read_clean(root):
    _send_back(root)
    out, (rep,) = read(1, root=root)
    assert rep.clean, rep.gaps()
    assert set(TARGET) <= set(rep.driven)
    assert all(a["status"] in ("acked", "already_in_sink") for a in rep.docs.values())
    draft = yaml.safe_load((out / f"{FOLDER}.evidence.draft.yaml").read_text())
    assert draft["rows"] == sorted(TARGET) and draft["firm_cui"] == "1001012"
    assert draft["approved"].startswith("PENDING")  # the owner approves it, not the kit
    assert "**Clean**" in (out / "REPORT.md").read_text()


def test_saga_booking_otherwise_is_a_semantic_difference(root):
    m = month(firm("platitor"), "2026-05")
    p1 = m.docs["p1"].number
    _send_back(root, simulated_exports(m.book.amount_differs("p1", 100), ["2026-05"]))
    _out, (rep,) = read(1, root=root)
    assert not rep.clean
    assert any(p1.replace("-", "").replace(" ", "") in x for x in rep.meaning), rep.meaning
    assert ("semantic", next(f"meaning: {x}" for x in rep.meaning)) in rep.gaps()


def test_missing_or_foreign_exports_are_mechanical(root):
    out = _send_back(root)
    (out / "vanzari-2026-05.xls").unlink()
    other = month(firm("incasare"), "2026-05")
    (out / "rj.xls").write_bytes(simulated_exports(other.book, ["2026-05"])["rj.xls"])
    _out, (rep,) = read(1, root=root)
    assert any("vanzari-2026-05" in x and "missing" in x for x in rep.reader)
    assert any("an export of firm" in x for x in rep.reader)
    assert not rep.clean


def test_a_package_that_is_not_what_was_imported(root):
    _send_back(root)
    imported = next((root / "loop-01/prepared" / FOLDER / "import").glob("run-*/F_*"))
    imported.write_text(imported.read_text().replace("<Facturi>", "<Facturi>\n<!-- changed -->"))
    _out, (rep,) = read(1, root=root)
    assert any("differs from what was imported" in x for x in rep.package)


def test_the_cli(root, capsys):
    _send_back(root)
    assert main(["read", "1", "--root", str(root)]) == 0
    assert f"{FOLDER}: clean" in capsys.readouterr().out
