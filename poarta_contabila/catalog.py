"""Catalog Cale loader (WP-01): Lane B YAML → one checked, read-only registry.

Every YAML under ``catalog/`` declares ``catalog: <Name>``. One file per name is
the base; files with ``mode: additive`` append rows to it (``60_harvest``).
Anything unexpected fails closed with :class:`CatalogError`: unparseable YAML,
an unknown catalog name, two base files, a duplicate id, a reference to an
articol / module / HITL kind / graph / control that does not exist, or a
WriteModule outside its closed enums.
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from poarta_contabila.types import WriteModule

DEFAULT_CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog"

# catalog name -> [(list key, id field), ...]; the first entry is the one additive files extend.
_ROWS: dict[str, list[tuple[str, str]]] = {
    "ArticolePins": [("pins", "pins_id")],
    "ArticoleCoDitT": [("hard", "id")],
    "ArticoleCoDitPairs": [("hard", "id"), ("soft", "id")],
    "ArticoleCoDitAxes": [],
    "ArticoleSourceDoc": [("rows", "source_doc_id")],
    "ArticoleJobs": [("jobs", "job_kind")],
    "ArticoleGraph": [("graphs", "graph_id")],
    "ArticoleFlux": [("flux", "articol_id")],
    "ArticolBon": [("rows", "articol_id")],
    "ArticoleWriteModule": [("modules", "module_id")],
    "ArticoleReconcile": [("flux", "articol_id"), ("profiles", "profile_id")],
    "ArticoleClose": [("kinds", "close_kind")],
    "ArticoleHITL": [("kinds", "kind")],
    "JevAnnex": [("decisions", "decision_id")],
    "JevValidateV": [("gates", "id")],
    "ArticoleControls": [("controls", "control_id")],
    "ArticoleFiling": [("filings", "filing_id")],
    "ArticoleExtrasGrain": [],
}

# Illustrations, not law (they carry no ``catalog:`` key).
_SKIP_SUFFIX = "_EXAMPLE_"


class CatalogError(ValueError):
    """The catalog cannot be loaded as law."""


class UnknownArticol(CatalogError):
    """An ``articol_id`` that is not a row of the catalog (or not on that graph)."""


class UnknownHitlKind(CatalogError):
    """An interrupt kind that is not in ArticoleHITL (or not allowed on that graph)."""


Row = dict[str, Any]


@dataclass(frozen=True)
class Catalog:
    """Read-only view of the merged Lane B catalog."""

    docs: dict[str, Row]
    articole: dict[str, Row]
    graphs: dict[str, Row]
    source_docs: dict[str, Row]
    jobs: dict[str, Row]
    write_modules: dict[str, WriteModule]
    bon: dict[str, Row]
    hitl: dict[str, Row]
    controls: dict[str, Row]
    filings: dict[str, Row]
    close_kinds: dict[str, Row]
    recon_profiles: dict[str, Row]
    pins: dict[str, Row]
    sources: dict[str, list[str]] = field(default_factory=dict)

    def enums(self, catalog: str) -> dict[str, Any]:
        return self.docs[catalog].get("enums") or {}

    def articol(self, articol_id: str) -> Row:
        try:
            return self.articole[articol_id]
        except KeyError:
            raise UnknownArticol(f"unknown articol_id {articol_id!r}") from None

    def bind_articol(self, graph_id: str, articol_id: str) -> Row:
        """The articol de cale *articol_id*, if it exists and *graph_id* may walk it."""
        row = self.articol(articol_id)
        if articol_id not in (self._graph(graph_id).get("allowed_flux") or []):
            raise UnknownArticol(f"articol {articol_id!r} is not allowed on graph {graph_id!r}")
        return row

    def hitl_kind(self, kind: str, graph_id: str | None = None) -> Row:
        """The ArticoleHITL row for *kind*; with *graph_id*, it must be allowed there."""
        row = self.hitl.get(kind)
        if row is None:
            raise UnknownHitlKind(f"unknown HITL kind {kind!r}")
        if graph_id is not None and kind not in self.allowed_hitl(graph_id):
            raise UnknownHitlKind(f"HITL kind {kind!r} is not allowed on graph {graph_id!r}")
        return row

    def allowed_hitl(self, graph_id: str) -> set[str]:
        """``graph.allowed_hitl`` plus additive kinds that name this graph."""
        graph = self._graph(graph_id)
        extra = {k for k, row in self.hitl.items() if graph_id in (row.get("graph_ids") or [])}
        return set(graph.get("allowed_hitl") or []) | extra

    def _graph(self, graph_id: str) -> Row:
        try:
            return self.graphs[graph_id]
        except KeyError:
            raise CatalogError(f"unknown graph_id {graph_id!r}") from None


def load_catalog(root: str | Path | None = None) -> Catalog:
    """Load and check every catalog file under *root* (default: the repo's ``catalog/``)."""
    root = Path(root or os.environ.get("POARTA_CATALOG_DIR") or DEFAULT_CATALOG_DIR)
    if not root.is_dir():
        raise CatalogError(f"catalog directory not found: {root}")
    docs, sources = _merge(_read_all(root))
    cat = _index(docs, sources)
    _check_references(cat)
    return cat


def _read_all(root: Path) -> list[tuple[Path, Row]]:
    out = []
    for path in sorted(root.rglob("*.yaml")):
        if _SKIP_SUFFIX in path.name:
            continue
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise CatalogError(f"{path.name}: not valid YAML: {exc}") from None
        if not isinstance(doc, dict) or "catalog" not in doc:
            raise CatalogError(f"{path.name}: missing top-level 'catalog:' key")
        if doc["catalog"] not in _ROWS:
            raise CatalogError(f"{path.name}: unknown catalog {doc['catalog']!r}")
        out.append((path, doc))
    return out


def _merge(files: list[tuple[Path, Row]]) -> tuple[dict[str, Row], dict[str, list[str]]]:
    by_name: dict[str, list[tuple[Path, Row]]] = defaultdict(list)
    for path, doc in files:
        by_name[doc["catalog"]].append((path, doc))
    docs, sources = {}, {}
    for name, entries in by_name.items():
        bases = [(p, d) for p, d in entries if d.get("mode") != "additive"]
        if len(bases) != 1:
            names = ", ".join(p.name for p, _ in bases) or "none"
            raise CatalogError(
                f"{name}: needs exactly one base file and the rest 'mode: additive' (base: {names})"
            )
        base = dict(bases[0][1])
        sources[name] = [bases[0][0].name]
        list_key = _ROWS[name][0][0] if _ROWS[name] else None
        for path, add in entries:
            if add.get("mode") != "additive":
                continue
            if list_key is None or list_key not in add:
                raise CatalogError(f"{path.name}: additive file must add '{list_key}'")
            base[list_key] = list(base.get(list_key) or []) + list(add[list_key])
            sources[name].append(path.name)
        docs[name] = base
    return docs, sources


def _rows(docs: dict[str, Row], name: str, list_key: str, id_field: str) -> dict[str, Row]:
    out: dict[str, Row] = {}
    for row in (docs.get(name) or {}).get(list_key) or []:
        rid = row.get(id_field) if isinstance(row, dict) else None
        if not rid:
            raise CatalogError(f"{name}.{list_key}: row without '{id_field}': {row!r}")
        if rid in out:
            raise CatalogError(f"{name}: duplicate {id_field} {rid!r}")
        out[rid] = row
    return out


def _index(docs: dict[str, Row], sources: dict[str, list[str]]) -> Catalog:
    for name in _ROWS:
        if name not in docs and name not in ("ArticoleCoDitAxes", "ArticoleExtrasGrain"):
            raise CatalogError(f"catalog {name} is missing")
    for name, specs in _ROWS.items():
        seen: set[str] = set()
        for list_key, id_field in specs:
            for rid in _rows(docs, name, list_key, id_field):
                if list_key != "profiles" and rid in seen:
                    raise CatalogError(f"{name}: duplicate id {rid!r}")
                seen.add(rid)

    flux = _rows(docs, "ArticoleFlux", "flux", "articol_id")
    recon = _rows(docs, "ArticoleReconcile", "flux", "articol_id")
    clash = set(flux) & set(recon)
    if clash:
        raise CatalogError(f"articol_id in both Flux and Reconcile: {sorted(clash)}")

    modules: dict[str, WriteModule] = {}
    for mid, row in _rows(docs, "ArticoleWriteModule", "modules", "module_id").items():
        try:
            modules[mid] = WriteModule.model_validate(row)
        except ValidationError as exc:
            raise CatalogError(f"WriteModule {mid!r}: {exc}") from None

    return Catalog(
        docs=docs,
        articole={**flux, **recon},
        graphs=_rows(docs, "ArticoleGraph", "graphs", "graph_id"),
        source_docs=_rows(docs, "ArticoleSourceDoc", "rows", "source_doc_id"),
        jobs=_rows(docs, "ArticoleJobs", "jobs", "job_kind"),
        write_modules=modules,
        bon=_rows(docs, "ArticolBon", "rows", "articol_id"),
        hitl=_rows(docs, "ArticoleHITL", "kinds", "kind"),
        controls=_rows(docs, "ArticoleControls", "controls", "control_id"),
        filings=_rows(docs, "ArticoleFiling", "filings", "filing_id"),
        close_kinds=_rows(docs, "ArticoleClose", "kinds", "close_kind"),
        recon_profiles=_rows(docs, "ArticoleReconcile", "profiles", "profile_id"),
        pins=_rows(docs, "ArticolePins", "pins", "pins_id"),
        sources=sources,
    )


def _check_references(cat: Catalog) -> None:
    errors: list[str] = []

    def need(ids, known, where: str) -> None:
        for i in ids or []:
            if i not in known:
                errors.append(f"{where}: unknown {i!r}")

    for gid, g in cat.graphs.items():
        need(g.get("allowed_flux"), cat.articole, f"ArticoleGraph.{gid}.allowed_flux")
        need(g.get("allowed_hitl"), cat.hitl, f"ArticoleGraph.{gid}.allowed_hitl")
    for aid, a in cat.articole.items():
        if a.get("graph_id") not in cat.graphs:
            errors.append(f"articol {aid}: unknown graph_id {a.get('graph_id')!r}")
        elif aid not in (cat.graphs[a["graph_id"]].get("allowed_flux") or []):
            errors.append(f"articol {aid}: not in ArticoleGraph.{a['graph_id']}.allowed_flux")
        need(a.get("write_modules"), cat.write_modules, f"articol {aid}.write_modules")
        if "profile_id" in a:
            need([a["profile_id"]], cat.recon_profiles, f"articol {aid}.profile_id")
    for mid, m in cat.write_modules.items():
        need(m.used_by_flux, cat.articole, f"WriteModule.{mid}.used_by_flux")
        for aid in m.used_by_flux:
            if aid in cat.articole and mid not in (cat.articole[aid].get("write_modules") or []):
                errors.append(
                    f"WriteModule.{mid}.used_by_flux lists {aid!r}, which does not use it"
                )
    for aid, a in cat.articole.items():
        for mid in a.get("write_modules") or []:
            if mid in cat.write_modules and aid not in cat.write_modules[mid].used_by_flux:
                errors.append(f"articol {aid} uses {mid!r}, missing from its used_by_flux")
    for jk, j in cat.jobs.items():
        if j.get("graph_id") not in cat.graphs:
            errors.append(f"ArticoleJobs.{jk}: unknown graph_id {j.get('graph_id')!r}")
        need(j.get("source_doc_ids"), cat.source_docs, f"ArticoleJobs.{jk}.source_doc_ids")
        need(j.get("allowed_flux"), cat.articole, f"ArticoleJobs.{jk}.allowed_flux")
        need(j.get("hitl_kinds"), cat.hitl, f"ArticoleJobs.{jk}.hitl_kinds")
    for sid, s in cat.source_docs.items():
        need(s.get("flux_candidates"), cat.articole, f"ArticoleSourceDoc.{sid}.flux_candidates")
        if s.get("split"):
            need(s["split"].get("children"), cat.source_docs, f"ArticoleSourceDoc.{sid}.split")
            need([s["split"].get("hitl")], cat.hitl, f"ArticoleSourceDoc.{sid}.split.hitl")
            if s.get("posting_eligible"):
                errors.append(
                    f"ArticoleSourceDoc.{sid}: a split container cannot be posting_eligible"
                )
    for bid, b in cat.bon.items():
        need([b.get("write_module")], cat.write_modules, f"ArticolBon.{bid}.write_module")
    for ck, c in cat.close_kinds.items():
        need([c.get("articol_id")], cat.articole, f"ArticoleClose.{ck}.articol_id")
        need([c.get("recon_flux")], cat.articole, f"ArticoleClose.{ck}.recon_flux")
    for kind, h in cat.hitl.items():
        need(h.get("graph_ids"), cat.graphs, f"ArticoleHITL.{kind}.graph_ids")
    for fid, f in cat.filings.items():
        need(f.get("books_gate"), cat.controls, f"ArticoleFiling.{fid}.books_gate")

    if errors:
        raise CatalogError("catalog references do not resolve:\n  " + "\n  ".join(errors))
