"""folder_triage (WP-02): a Pack either passes every emit gate or it does not become a Job.

Gates (HANDBOOK §4, ARCHITECTURE §2): class ∧ identity ∧ primary ∧ the pack's
``emit`` JsonLogic rule, then a job_kind from ArticoleJobs. Fail closed: any
gate that cannot be evaluated is a failed gate. Jev is not consulted here; the
caller supplies ``source_doc_id`` (sniff) and the graph asks a human when it is
``unknown`` or a receipt's CUI is unclear.

A container (a SourceDoc row with ``split``, e.g. ``decont_cheltuieli``, A2) never
emits. When its own identity and primary gates pass, the graph asks ``decont_split``
for its parts; each part becomes a child Pack (same tenant, firm folder and period,
its own hash) that passes or fails the same gates. XML first: a part that has the
invoice XML is a ``ro_efactura_ubl`` part, never a PDF part.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import Field

from poarta_contabila import jsonlogic
from poarta_contabila.catalog import Catalog, CatalogError
from poarta_contabila.hitl import ask
from poarta_contabila.types import Closed, Cui, Period, PrimaryKind, Slug, cui_is_valid

_XML_KINDS = ("ubl_spv", "xml")

GRAPH_ID = "folder_triage"
THREAD_PREFIX = "batch:"


class Pack(Closed):
    """A normalized source-document dossier before emit (facts, not judgments)."""

    tenant_cui: Cui
    saga_firm_folder: str
    punct: str = "default"
    period: Period
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_doc_id: Slug
    kinds: list[PrimaryKind]
    our_role: Literal["inbound", "outbound", "n/a"]
    counterparty_cui: str | None = None
    identity_ok: bool = False
    is_storno: bool = False
    bon_our_cui_on_doc: bool | None = None


class EmitDecision(Closed):
    emit: bool
    job_kind: Slug | None = None
    aisle: str
    failed: list[str] = Field(default_factory=list)


def _context(pack: Pack, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_doc": row,
        "source_doc_id": pack.source_doc_id,
        "fiscal_class": row.get("fiscal_class"),
        "primary_kind": "ubl_spv" if "ubl_spv" in pack.kinds else (pack.kinds or [None])[0],
        "identity_ok": pack.identity_ok,
        "bon": {"our_cui_on_doc": pack.bon_our_cui_on_doc},
    }


def _aisle(pack: Pack, ctx: dict[str, Any]) -> str:
    template = jsonlogic.apply(jsonlogic.rule("route_aisle"), ctx) or "90_unknown/"
    return template.format(
        role=pack.our_role,
        cui=pack.counterparty_cui or "_fara_cui",
        id=pack.counterparty_cui or pack.source_hash[:12],
        period=pack.period,
    )


def _job_kind(cat: Catalog, pack: Pack) -> str | None:
    if pack.is_storno:
        storno = cat.jobs.get("job_storno") or {}
        return "job_storno" if pack.source_doc_id in (storno.get("source_doc_ids") or []) else None
    kinds = [
        k
        for k, row in cat.jobs.items()
        if k != "job_storno" and pack.source_doc_id in (row.get("source_doc_ids") or [])
    ]
    return kinds[0] if len(kinds) == 1 else None


def decide_emit(cat: Catalog, pack: Pack) -> EmitDecision:
    """Evaluate every emit gate for *pack*; the decision lists each gate that failed."""
    row = cat.source_docs.get(pack.source_doc_id)
    if row is None:
        raise CatalogError(f"unknown source_doc_id {pack.source_doc_id!r}")
    ctx = _context(pack, row)
    failed: list[str] = []

    if not row.get("posting_eligible"):
        failed.append("class_gate")

    primary = row.get("primary") or {}
    has_primary = any(k in pack.kinds for k in primary.get("required_kinds") or [])
    if not has_primary and not row.get("emit_on_incomplete"):
        failed.append("primary_gate")

    identity = row.get("identity") or {}
    if identity.get("needs_tenant_on_doc") and not pack.identity_ok:
        failed.append("identity_gate")
    if identity.get("needs_counterparty_cui") and not (
        pack.counterparty_cui and cui_is_valid(pack.counterparty_cui)
    ):
        failed.append("identity_gate")
    if identity.get("bon_cui_fork") and pack.bon_our_cui_on_doc is None:
        failed.append("bon_fork")

    if not jsonlogic.apply(jsonlogic.rule("emit"), ctx):
        failed.append("emit_rule")

    job_kind = _job_kind(cat, pack)
    if job_kind is None:
        failed.append("job_kind")

    failed = list(dict.fromkeys(failed))
    return EmitDecision(
        emit=not failed,
        job_kind=job_kind if not failed else None,
        aisle=_aisle(pack, ctx),
        failed=failed,
    )


# ----- graph -----


class DefineClassResume(Closed):
    source_doc_id: Slug


class BonCuiResume(Closed):
    cu_cui: bool
    fara_cui: bool


class SplitPart(Closed):
    part_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_doc_id: Slug
    kinds: list[PrimaryKind] = Field(min_length=1)
    bon_our_cui_on_doc: bool | None = None
    counterparty_cui: Cui | None = None


class DecontSplitResume(Closed):
    parts: list[SplitPart] = Field(min_length=1)


def check_split(cat: Catalog, container: Pack, answer: DecontSplitResume) -> str | None:
    """Why a ``decont_split`` answer cannot be used, or None (the HITL ``cannot`` list)."""
    split = cat.source_docs[container.source_doc_id]["split"]
    hashes = [p.part_hash for p in answer.parts]
    if len(set(hashes)) != len(hashes) or container.source_hash in hashes:
        return "every part needs its own hash, different from the container's"
    for i, part in enumerate(answer.parts, start=1):
        if part.source_doc_id not in split["children"]:
            return f"part {i}: {part.source_doc_id!r} is not one of {split['children']}"
        if part.source_doc_id == "ro_efactura_pdf" and any(k in part.kinds for k in _XML_KINDS):
            return f"part {i}: the invoice XML exists, so the part is ro_efactura_ubl, not a PDF"
        row = cat.source_docs[part.source_doc_id]
        if (row.get("identity") or {}).get("bon_cui_fork") and part.bon_our_cui_on_doc is None:
            return f"part {i}: say whether our CUI is on the receipt (bon_our_cui_on_doc)"
    return None


def child_pack(cat: Catalog, container: Pack, part: SplitPart) -> Pack:
    """A part of a container as a Pack of its own (inherits tenant, folder, period)."""
    role = cat.source_docs[part.source_doc_id].get("our_role_default")
    if role not in ("inbound", "outbound", "n/a"):
        role = cat.source_docs[container.source_doc_id].get("our_role_default", "inbound")
    return Pack(
        tenant_cui=container.tenant_cui,
        saga_firm_folder=container.saga_firm_folder,
        punct=container.punct,
        period=container.period,
        source_hash=part.part_hash,
        source_doc_id=part.source_doc_id,
        kinds=part.kinds,
        our_role=role,
        counterparty_cui=part.counterparty_cui,
        identity_ok=container.identity_ok,
        bon_our_cui_on_doc=part.bon_our_cui_on_doc,
    )


class TriageState(TypedDict, total=False):
    pack: dict[str, Any]
    decision: dict[str, Any]
    split: bool
    children: list[dict[str, Any]]
    job_id: str | None
    created: bool


def build_triage_graph(cat: Catalog, store: Any, *, checkpointer: Any):
    """Compile the folder_triage graph. Edges read stored fields only."""
    cat.hitl_kind("define_class", graph_id=GRAPH_ID)
    cat.hitl_kind("bon_cui_unclear", graph_id=GRAPH_ID)
    for row in cat.source_docs.values():
        if row.get("split"):
            cat.hitl_kind(row["split"]["hitl"], graph_id=GRAPH_ID)

    def gate(state: TriageState, config) -> TriageState:
        thread = config["configurable"]["thread_id"]
        if not str(thread).startswith(THREAD_PREFIX):
            raise ValueError(f"folder_triage runs on '{THREAD_PREFIX}' threads, got {thread!r}")
        pack = Pack.model_validate(state["pack"])

        if pack.source_doc_id == "unknown":
            answer = ask(
                "define_class",
                {"source_hash": pack.source_hash},
                DefineClassResume,
                lambda a: (
                    None
                    if a.source_doc_id in cat.source_docs and a.source_doc_id != "unknown"
                    else f"unknown source_doc_id {a.source_doc_id!r}"
                ),
            )
            pack = pack.model_copy(update={"source_doc_id": answer.source_doc_id})

        row = cat.source_docs.get(pack.source_doc_id) or {}
        if (row.get("identity") or {}).get("bon_cui_fork") and pack.bon_our_cui_on_doc is None:
            answer = ask(
                "bon_cui_unclear",
                {"source_hash": pack.source_hash},
                BonCuiResume,
                lambda a: (
                    None if a.cu_cui != a.fara_cui else "choose exactly one of cu_cui / fara_cui"
                ),
            )
            pack = pack.model_copy(update={"bon_our_cui_on_doc": answer.cu_cui})

        decision = decide_emit(cat, pack)
        # a container is split only when it is the tenant's and its primary is there
        split = bool(row.get("split")) and not (
            {"identity_gate", "primary_gate"} & set(decision.failed)
        )
        return {"pack": pack.model_dump(), "decision": decision.model_dump(), "split": split}

    def split(state: TriageState) -> TriageState:
        container = Pack.model_validate(state["pack"])
        row = cat.source_docs[container.source_doc_id]
        answer = ask(
            row["split"]["hitl"],
            {"source_hash": container.source_hash, "children": row["split"]["children"]},
            DecontSplitResume,
            lambda a: check_split(cat, container, a),
        )
        children = []
        for part in answer.parts:
            child = child_pack(cat, container, part)
            children.append(
                {"pack": child.model_dump(), "decision": decide_emit(cat, child).model_dump()}
            )
        return {"children": children}

    def emit(state: TriageState) -> TriageState:
        pack = Pack.model_validate(state["pack"])
        result = store.emit(pack, EmitDecision.model_validate(state["decision"]))
        return {"job_id": result.job.job_id, "created": result.created}

    def emit_children(state: TriageState) -> TriageState:
        out = []
        for child in state["children"]:
            decision = EmitDecision.model_validate(child["decision"])
            job_id, created = None, False
            if decision.emit:
                result = store.emit(Pack.model_validate(child["pack"]), decision)
                job_id, created = result.job.job_id, result.created
            out.append({**child, "job_id": job_id, "created": created})
        return {"children": out}

    def route(state: TriageState) -> str:
        if state.get("split"):
            return "split"
        return "emit" if state["decision"]["emit"] else END

    g = StateGraph(TriageState)
    g.add_node("gate", gate)
    g.add_node("split", split)
    g.add_node("emit", emit)
    g.add_node("emit_children", emit_children)
    g.add_edge(START, "gate")
    g.add_conditional_edges("gate", route, ["split", "emit", END])
    g.add_edge("split", "emit_children")
    g.add_edge("emit", END)
    g.add_edge("emit_children", END)
    return g.compile(checkpointer=checkpointer)
