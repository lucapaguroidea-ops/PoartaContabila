"""Unit tests for Jev annex validation (V0–V8).

Run: pytest artifacts/test_jev_validate.py -q
Stand-alone: copies the validator so the file does not need the app pkg.
"""

from __future__ import annotations

from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError


# ----- contract under test (keep in sync with JEV_ANNEX_v1) -----

class JevOut(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision_id: str
    choice_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    prompt_hash: str


DecisionResult = Literal["accept", "hitl", "reject"]


ANNEX = {
    "jev_source_doc": {
        "node": "folder_triage.sniff",
        "choices": {
            "ro_efactura_ubl",
            "ro_efactura_pdf",
            "bon_fiscal",
            "unknown",
        },
        "threshold": 0.65,
        "hitl_kind": "define_class",
        "only_if": None,
        "matches_ids": None,
    },
    "jev_bon_cui_present": {
        "node": "folder_triage.bon_fork",
        "choices": {"true", "false", "unclear"},
        "threshold": 0.65,
        "hitl_kind": "bon_cui_unclear",
        "only_if": lambda ctx: ctx.get("source_doc_id") == "bon_fiscal",
        "matches_ids": None,
    },
    "jev_flux": {
        "node": "ingest.bind_articol",
        "choices": {"ro_efactura_inbound", "ro_efactura_outbound", "bon_cu_cui"},
        "threshold": 0.0,
        "hitl_kind": "define_articol",
        "only_if": None,
        "matches_ids": "cands",
    },
}

FROZEN_HASH = "jev-annex-ex-2026-03-30"
PARENT_ACTIVE = {
    "ro_efactura_ubl",
    "ro_efactura_pdf",
    "bon_fiscal",
    "unknown",
    "true",
    "false",
    "unclear",
    "ro_efactura_inbound",
    "ro_efactura_outbound",
    "bon_cu_cui",
}


def validate_jev(
    raw: dict[str, Any],
    *,
    node: str,
    ctx: dict[str, Any],
    frozen_hash: str = FROZEN_HASH,
) -> tuple[DecisionResult, str | None]:
    try:
        out = JevOut.model_validate(raw)
    except ValidationError:
        return "reject", "v0_shape"

    row = ANNEX.get(out.decision_id)
    if row is None:
        return "reject", "v2_unknown_decision"
    if row["node"] != node:
        return "reject", "v2_wrong_node"
    if out.prompt_hash != frozen_hash:
        return "reject", "v1_hash"

    only_if = row["only_if"]
    if callable(only_if) and not only_if(ctx):
        return "reject", "v4_only_if"

    if out.choice_id not in row["choices"]:
        return "hitl", row["hitl_kind"]

    if out.choice_id not in PARENT_ACTIVE:
        return "hitl", row["hitl_kind"]

    if out.confidence < row["threshold"]:
        return "hitl", row["hitl_kind"]

    if row["matches_ids"]:
        cands = set(ctx.get("cands") or [])
        if out.choice_id not in cands:
            return "hitl", row["hitl_kind"]

    if out.choice_id in {"unknown", "unclear", "altele"}:
        return "hitl", row["hitl_kind"]

    return "accept", None


def _src(**over: Any) -> dict[str, Any]:
    base = {
        "decision_id": "jev_source_doc",
        "choice_id": "bon_fiscal",
        "confidence": 0.81,
        "prompt_hash": FROZEN_HASH,
    }
    base.update(over)
    return base


# ----- tests -----

def test_accept_bon_fiscal():
    assert validate_jev(_src(), node="folder_triage.sniff", ctx={}) == (
        "accept",
        None,
    )


def test_v0_rejects_extra_field():
    raw = _src(tva_deducere="full")
    assert validate_jev(raw, node="folder_triage.sniff", ctx={})[0] == "reject"


def test_v0_rejects_confidence_string():
    raw = _src()
    raw["confidence"] = "0.81"
    assert validate_jev(raw, node="folder_triage.sniff", ctx={}) == (
        "reject",
        "v0_shape",
    )


def test_off_list_goes_to_define_class():
    assert validate_jev(
        _src(choice_id="factura_simplificata"),
        node="folder_triage.sniff",
        ctx={},
    ) == ("hitl", "define_class")


def test_wrong_node_rejected():
    assert validate_jev(_src(), node="ingest.nature_bind", ctx={}) == (
        "reject",
        "v2_wrong_node",
    )


def test_stale_prompt_hash_rejected():
    assert validate_jev(
        _src(prompt_hash="old"),
        node="folder_triage.sniff",
        ctx={},
    ) == ("reject", "v1_hash")


def test_low_confidence_hitl():
    assert validate_jev(
        _src(confidence=0.40),
        node="folder_triage.sniff",
        ctx={},
    ) == ("hitl", "define_class")


def test_unknown_is_hitl_even_if_listed():
    assert validate_jev(
        _src(choice_id="unknown", confidence=0.99),
        node="folder_triage.sniff",
        ctx={},
    ) == ("hitl", "define_class")


def test_bon_cui_only_if_bon():
    raw = {
        "decision_id": "jev_bon_cui_present",
        "choice_id": "true",
        "confidence": 0.9,
        "prompt_hash": FROZEN_HASH,
    }
    assert validate_jev(raw, node="folder_triage.bon_fork", ctx={})[0] == "reject"
    assert (
        validate_jev(
            raw,
            node="folder_triage.bon_fork",
            ctx={"source_doc_id": "bon_fiscal"},
        )[0]
        == "accept"
    )


def test_flux_must_be_in_matches_survivors():
    raw = {
        "decision_id": "jev_flux",
        "choice_id": "ro_efactura_outbound",
        "confidence": 0.99,
        "prompt_hash": FROZEN_HASH,
    }
    ctx = {"cands": ["ro_efactura_inbound"]}
    assert validate_jev(raw, node="ingest.bind_articol", ctx=ctx) == (
        "hitl",
        "define_articol",
    )
    ctx = {"cands": ["ro_efactura_inbound", "ro_efactura_outbound"]}
    assert validate_jev(raw, node="ingest.bind_articol", ctx=ctx)[0] == "accept"
