"""The wired gate: stores, bucket, checkpointer, the ingest graph and the agent service.

``build_runtime`` takes every part explicitly (tests pass in-memory ones);
``runtime_from_env`` builds the production one from ``DATABASE_URL`` and ``S3_*``.
Parts not wired fail closed: without Jev (``JEV_BASE_URL`` + ``JEV_API_KEY``) every document
is asked (``v3_approve``) and the close gets no Layer 2 suggestion; a tenant without an
uploaded journal export gets ``need_rj_export``.
"""

from __future__ import annotations

import hashlib
import io
import os
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from langgraph.types import Command

from poarta_contabila.agent import AgentService
from poarta_contabila.answers import InMemoryAnswerLog
from poarta_contabila.answers import record as record_answer
from poarta_contabila.catalog import Catalog
from poarta_contabila.close import CloseDeps, InMemoryCloseStore, build_close_graph
from poarta_contabila.codit import Codit, CoditInput, write_codit
from poarta_contabila.extract.contract import (
    Extraction,
    InMemoryExtractStore,
    read_extraction,
    write_extraction,
)
from poarta_contabila.extract.document_ai import DocumentAiError, shows_iban
from poarta_contabila.extract.gemini import GeminiError, OutOfQuota, gemini_reader_from_env
from poarta_contabila.extract.statement import (
    StatementError,
    StatementMeta,
    line_source_hash,
    parse_statement,
    statement_line_document,
)
from poarta_contabila.extract.ubl import UblError, parse_ubl, read_spv_zip, to_canonical
from poarta_contabila.filings import due_filings
from poarta_contabila.filings import views as filing_views
from poarta_contabila.ingest import IngestDeps, build_ingest_graph, start_payload
from poarta_contabila.jev import (
    InMemoryJevCache,
    Jev,
    make_judge,
    make_recon_review,
    make_v2,
    role_pin,
    role_transport,
)
from poarta_contabila.model_roles import CALL_MODES, InMemoryModelCallStore, ModelGateway, brief
from poarta_contabila.packages import BlobStore, PackageStore
from poarta_contabila.period_diff import ExpectedJob, build_period_diff, can_file
from poarta_contabila.provider_policy import (
    InMemoryPolicyStore,
    InMemoryRoleChoiceStore,
    PostgresPolicyStore,
    PostgresRoleChoiceStore,
    RoleChoice,
    Router,
)
from poarta_contabila.reading_waits import (
    InMemoryReadingChoiceStore,
    InMemoryReadingWaitStore,
    ReadingChoice,
    ReadingWait,
)
from poarta_contabila.recon.post import PostResult, how_check
from poarta_contabila.recon.pre import PreResult, ReconStore, make_pre_check, pre_profile
from poarta_contabila.recon.settle import (
    SETTLES,
    InvoiceJob,
    SettlementProposal,
    propose_settlement,
    settle_key,
)
from poarta_contabila.reconcile import PostDeps, ReconDeps, WaitingJob, build_reconcile_graph
from poarta_contabila.registry import (
    ExportKind,
    Product,
    Tenant,
    check_export,
    export_row,
    rj_eye,
    witnesses_provider,
)
from poarta_contabila.triage import (
    InMemoryBatchIndex,
    Pack,
    PostgresBatchIndex,
    build_triage_graph,
    decide_emit,
)
from poarta_contabila.types import CanonicalDocument, JobRecord, SourceRef, TenantRef

SETTLE_MONTHS = 3
"""A bank line looks for the invoice it settles in its own month and the two before it."""


def _months_back(period: str, n: int) -> list[str]:
    year, month = int(period[:4]), int(period[5:])
    out = []
    for _ in range(n):
        out.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return out


class IngestRefused(ValueError):
    """The upload cannot become a Job; the message says which gate."""


class ReadingDeferred(Exception):
    """No model can read this statement now (00_LAW §8 A5): it waits, nothing is refused."""

    def __init__(self, reason: str, retry_after: float):
        super().__init__(reason)
        self.reason, self.retry_after = reason, retry_after


def statement_problem(
    extraction: Extraction, meta: StatementMeta, cui: str, *, tie: bool = True
) -> str | None:
    """Why a read statement does not confirm, or None: the holder CUI, the IBAN, and (with
    *tie*) every line tying opening − debits + credits = closing."""
    if not extraction.meta.identity_ok:
        return f"stmt_no_identity: the statement does not show CUI {cui}"
    if not shows_iban(extraction.markdown, meta.iban):
        return f"the statement does not show the IBAN {meta.iban}"
    if tie:
        try:
            parse_statement(extraction.tables, meta, cui)
        except StatementError as exc:
            return str(exc)
    return None


@dataclass
class Runtime:
    catalog: Catalog
    jobs: Any
    packages: PackageStore
    blobs: BlobStore
    registry: Any
    recon: ReconStore | None
    agent_store: Any
    checkpointer: Any
    periods: Any = None  # InMemoryPeriodStore | PostgresPeriodStore
    rules: Any = None  # InMemoryRuleStore | PostgresRuleStore
    closes: Any = None  # InMemoryCloseStore | PostgresCloseStore
    codits: Any = None  # InMemoryCoditStore | PostgresCoditStore
    filings: Any = None  # InMemoryFilingStore | PostgresFilingStore
    jev: Any = None  # jev.Jev; None = not wired (fail closed)
    jev_cache: Any = None  # InMemoryJevCache | PostgresJevCache (answers paid for once)
    jev_http: Any = None  # httpx.Client for OpenRouter: Jev and System Two (tests); None = per call
    statement_reader: Any = None  # (pdf, *, tenant_cui) -> Extraction; DocumentAiReader
    gemini_reader: Any = None  # GeminiStatementReader: synthetic tenants only (WP-36)
    extracts: Any = None  # InMemoryExtractStore | PostgresExtractStore
    model_calls: Any = None  # InMemoryModelCallStore | PostgresModelCallStore
    model_mode: str = "off"  # MODEL_CALLS: off | dry (record only) | live (WP-36)
    answers: Any = None  # InMemoryAnswerLog | PostgresAnswerLog (WP-33)
    reading_waits: Any = None  # InMemoryReadingWaitStore | PostgresReadingWaitStore (WP-42)
    reading_choices: Any = None  # InMemoryReadingChoiceStore | Postgres… (WP-43)
    provider_policies: Any = None  # InMemoryPolicyStore | PostgresPolicyStore (WP-53)
    role_choices: Any = None  # InMemoryRoleChoiceStore | PostgresRoleChoiceStore (WP-53)
    batches: Any = None  # InMemoryBatchIndex | PostgresBatchIndex (WP-67)

    def __post_init__(self) -> None:
        if self.model_calls is None:
            self.model_calls = InMemoryModelCallStore()
        if self.answers is None:
            self.answers = InMemoryAnswerLog()
        if self.batches is None:
            self.batches = InMemoryBatchIndex()
        if self.model_mode not in CALL_MODES:
            self.model_mode = "off"  # an unknown mode calls nothing
        self.router = Router(
            policies=self.provider_policies or InMemoryPolicyStore(),
            choices=self.role_choices or InMemoryRoleChoiceStore(),
            http=self.jev_http,
        )
        if self.jev is None and self.model_mode in ("dry", "live"):
            self.jev = Jev(
                transport=role_transport(
                    self.catalog.model_roles,
                    mode=self.model_mode,
                    calls=self.model_calls,
                    synthetic=self._synthetic,
                    http=self.jev_http,
                    router=self.router,
                ),
                cache=self.jev_cache if self.jev_cache is not None else InMemoryJevCache(),
                pin=role_pin(self.catalog.model_roles),
            )
        self.gateway = ModelGateway(
            roles=self.catalog.model_roles,
            calls=self.model_calls,
            mode=self.model_mode,
            synthetic=self._synthetic,
            http=self.jev_http,
            router=self.router,
        )
        self.deps = IngestDeps(
            catalog=self.catalog,
            jobs=self.jobs,
            packages=self.packages,
            blobs=self.blobs,
            pre_check=make_pre_check(
                self.catalog, witnesses_provider(self.registry, self.blobs), store=self.recon
            ),
            judge=make_judge(self.jev),
            tenant_name=self._tenant_name,
            observe=self.gateway.observe,
            observe_question=self.gateway.observe_question,
        )
        self.ingest = build_ingest_graph(self.deps, checkpointer=self.checkpointer)
        self.agent = AgentService(
            catalog=self.catalog,
            jobs=self.jobs,
            packages=self.packages,
            blobs=self.blobs,
            store=self.agent_store,
            resume=lambda job_id, payload: self.resume(job_id, payload),
            canonical=self.canonical,
        )
        self.deps.snapshot_validated = self.agent.snapshot_validated
        self.deps.period_filed = lambda cui, period: (
            self.filings is not None and self.filings.has_receipt(cui, period)
        )
        if self.closes is None:
            self.closes = InMemoryCloseStore()
        if self.extracts is None:
            self.extracts = InMemoryExtractStore()
        if self.reading_waits is None:
            self.reading_waits = InMemoryReadingWaitStore()
        if self.reading_choices is None:
            self.reading_choices = InMemoryReadingChoiceStore()
        self.close = build_close_graph(
            CloseDeps(
                catalog=self.catalog,
                store=self.closes,
                expected=self.expected,
                eye=self._eye,
                rules=self.rules,
                period_store=self.periods,
                jev_v2=make_v2(self.jev, self.axes, lambda axes: due_filings(self.catalog, axes)),
                codit=lambda cui, period: (
                    self.codits.get(cui, period) if self.codits is not None else None
                ),
                codit_put=self.codits.put if self.codits is not None else None,
                observe_question=self.gateway.observe_question,
                recon_open=lambda cui, period: (
                    [w.job.job_id for w in self.recon_waiting(cui, period)]
                    + self.post_open(cui, period)
                ),
                stalled=lambda cui, period: self.stalled(cui, period),
                prior=lambda cui, period: self.prior(cui, period),
            ),
            checkpointer=self.checkpointer,
        )
        self.deps.posted_doc = self.agent.posted_doc
        self.deps.book_of_record = lambda cui: (
            t.book_of_record if (t := self.registry.tenant(cui)) is not None else "saga"
        )
        self.deps.treasury_account = self._treasury_account
        self.reconcile = build_reconcile_graph(
            ReconDeps(
                catalog=self.catalog,
                waiting=self.recon_waiting,
                recheck=lambda w: self.deps.pre_check(
                    w.job, w.doc, fiscal_class=w.fiscal_class, axes=w.axes
                ),
                settle=self._settle_pre,
                export_months=self._rj_export_months,
                review=make_recon_review(self.jev),
                observe_question=self.gateway.observe_question,
                post=PostDeps(
                    waiting=lambda cui, period: self.post_waiting(cui, period),
                    check=lambda w: self.post_check(w),
                    known=self._post_known,
                    settle=self._settle_post,
                ),
            ),
            checkpointer=self.checkpointer,
        )
        self.deps.settlement = self.settlement
        self.triage = build_triage_graph(self.catalog, self.jobs, checkpointer=self.checkpointer)

    # -- helpers --

    def _tenant_name(self, cui: str) -> str:
        tenant = self.registry.tenant(cui)
        if tenant is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        return tenant.name

    def _synthetic(self, cui: str | None) -> bool:
        tenant = self.registry.tenant(cui) if cui else None
        return tenant is not None and tenant.data_class == "synthetic"

    def model_roles_view(self) -> list[dict[str, Any]]:
        """Each model role: where it acts, its pinned model, and whether it could be called.

        Key variables are reported as set or not, never their values.
        """
        out = []
        for role in self.catalog.model_roles.values():
            out.append(
                {
                    **role.model_dump(mode="json"),
                    "key_env": role.key_env,
                    "key_set": bool(os.environ.get(role.key_env)),
                    "mode": self.model_mode,
                    "callable_in_dry_run": role.status == "wired" and role.model is not None,
                    "eu_route_set": role.eu_route is not None,
                    "eu_keys_set": (
                        all(
                            bool(os.environ.get(name))
                            for name in (role.eu_route.key_env, role.eu_route.project_env)
                            if name
                        )
                        if role.eu_route
                        else False
                    ),
                    "card_hash": role.card_hash,
                    "brief": brief(role),
                    "pin": self._pin_view(role),
                }
            )
        return out

    def key_usage(self) -> dict[str, Any]:
        """WP-56: OpenRouter's own figures for each key the catalog uses (``key_usage``)."""
        from poarta_contabila.key_usage import key_usage

        return key_usage(self.catalog.model_roles, http=self.jev_http)

    def _pin_view(self, role: Any) -> dict[str, Any] | None:
        """WP-53: the pin the data policy allows now, and why (OpenRouter roles)."""
        if role.route != "openrouter" or role.model is None:
            return None
        p = self.router.pick(role)
        choice = self.router.choices.latest(role.role_id)
        return {
            "on": p.on,
            "model": p.model,
            "provider": (p.provider or {}).get("only"),
            "reason": p.reason,
            "policies_checked_at": self.router.policies.checked_at(),
            "choice": choice.model_dump() if choice else None,
        }

    def role_choose(
        self, role_id: str, choice: str, until: str | None, operator: str | None
    ) -> dict[str, Any]:
        """WP-53 (00_LAW §8 A7): the operator's choice for a role no approved pin passes,
        kept with who chose it (``domain.model_role_choices``; the latest holds)."""
        role = self.catalog.model_roles.get(role_id)
        if role is None or role.route != "openrouter":
            raise IngestRefused(f"{role_id!r} is not an OpenRouter model role")
        if choice == "allow_synthetic" and not until:
            raise IngestRefused("allow_synthetic needs an until date (YYYY-MM-DD)")
        row = RoleChoice(
            role_id=role_id,
            choice=choice,
            until=until if choice == "allow_synthetic" else None,
            operator=operator,
            at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        self.router.choices.put(row)
        return {"role_id": role_id, "choice": row.model_dump(), "pin": self._pin_view(role)}

    def model_compare(
        self,
        role_id: str,
        inputs: int,
        runs: int,
        candidate: int | None = None,
        skip: int = 0,
    ) -> dict[str, Any]:
        """WP-59: the questions a System Two role last explained for synthetic tenants, each
        sent *runs* times to the main pin and to every approved alternate, first answer only
        (no retry). Returned, not recorded: a comparison decides nothing and feeds no node.
        *candidate*: 0 the main pin, N the Nth alternate (one at a time, WP-61); *skip*: start
        after that many of the latest questions."""
        from poarta_contabila.explain import ExplainError, send

        role = self.catalog.model_roles.get(role_id)
        if role is None or role.system != "system_two" or role.model is None:
            raise IngestRefused(f"{role_id!r} is not a System Two role with a model")
        if self.model_mode != "live":
            raise IngestRefused("MODEL_CALLS is not live: nothing is sent")
        secret = os.environ.get(role.key_env)
        if not secret:
            raise IngestRefused(f"{role.key_env} is not set")
        questions: dict[str, dict[str, Any]] = {}
        for call in self.model_calls.recent(role_id, 500):
            if call.tenant_cui and self._synthetic(call.tenant_cui):
                questions.setdefault(call.input_hash, call.input)
            if len(questions) == skip + inputs:
                break
        questions = dict(list(questions.items())[skip:])
        if not questions:
            raise IngestRefused(f"{role_id}: no synthetic question to compare on yet")
        candidates = [("main", role.model, role.provider.model_dump())] + [
            (f"alternate {i}", a.model, a.provider.model_dump())
            for i, a in enumerate(role.alternates, 1)
        ]
        if candidate is not None:
            if not 0 <= candidate < len(candidates):
                raise IngestRefused(f"{role_id} has no candidate {candidate}")
            candidates = [candidates[candidate]]
        out = []
        for on, model, provider in candidates:
            used = role.model_copy(update={"model": model})
            row: dict[str, Any] = {"on": on, "model": model, "provider": provider.get("only")}
            tries = []
            for payload in questions.values():
                for _ in range(runs):
                    try:
                        got = send(
                            used, payload, secret, http=self.jev_http, provider=provider, retries=0
                        )
                    except ExplainError as exc:
                        tries.append({"ok": False, "reason": str(exc)[:200]})
                    else:
                        tries.append(
                            {
                                "ok": True,
                                "served_by": got["served_by"],
                                "cost": got["usage"]["cost"],
                                "output_tokens": got["usage"]["output_tokens"],
                                "explanation": got["explanation"],
                            }
                        )
            costs = [t["cost"] for t in tries if t.get("cost") is not None]
            row.update(
                {
                    "first_try_ok": sum(t["ok"] for t in tries),
                    "tries": len(tries),
                    "cost_per_ok": round(sum(costs) / len(costs), 6) if costs else None,
                    "results": tries,
                }
            )
            out.append(row)
        return {"role_id": role_id, "questions": len(questions), "runs": runs, "candidates": out}

    def _treasury_account(self, cui: str, iban: str) -> str | None:
        tenant = self.registry.tenant(cui)
        return tenant.treasury_account(iban) if tenant else None

    @staticmethod
    def _cfg(job_id: str) -> dict:
        return {"configurable": {"thread_id": f"job:{job_id}"}}

    def canonical(self, job_id: str) -> CanonicalDocument:
        values = self.ingest.get_state(self._cfg(job_id)).values
        return CanonicalDocument.model_validate(values["canonical"])

    def view(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        state = self.ingest.get_state(self._cfg(job_id))
        question = next((i.value for t in state.tasks for i in t.interrupts), None)
        pre = (state.values or {}).get("pre") or {}
        return {
            "job": job.model_dump(),
            "pre": {k: pre.get(k) for k in ("verdict", "profile_id")} if pre else None,
            "question": question,
            "explanation": self.gateway.explanation(question, job.tenant.cui),
        }

    def resume(self, job_id: str, payload: Any, operator: str | None = None) -> dict[str, Any]:
        job = self.jobs.get(job_id)  # KeyError for an unknown job
        self._answer(
            self.ingest, self._cfg(job_id), "ingest_source_doc", job.tenant.cui, payload, operator
        )
        return self.view(job_id)

    # -- the review page's inbox (WP-66, 00_LAW §8 A8) --

    # a job in any of these may wait on a person; acked, already_in_sink, rejected, failed never do
    _OPEN_JOBS = (
        "ingested",
        "extracted",
        "bound",
        "reconcile_pre",
        "approved",
        "packaged",
        "wait_validare",
        "needs_human",
        "reopened",
    )

    def inbox(self, cui: str, period: str) -> dict[str, Any]:
        """Every question waiting on an accountant for *cui*: its open jobs (any month), its
        expense-report batches (WP-67), and the reconcile_sink and monthly_close runs of
        *period*. Each item names where its
        answer goes and the answer's shape (ArticoleHITL); a question for the SAGA agent is
        left out. A job that needs a person but asks nothing is listed with its error."""
        if self.registry.tenant(cui) is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        items = []
        for status in self._OPEN_JOBS:
            for job in self.jobs.by_status(status, cui):
                question = self._waiting(self.ingest, self._cfg(job.job_id))
                if question is None and status != "needs_human":
                    continue
                items.append(self._inbox_item(question, cui, f"/jobs/{job.job_id}/resume", job=job))
        for batch_id in self.batches.for_tenant(cui):
            question = self._waiting(self.triage, self._batch_cfg(batch_id))
            if question is not None:
                items.append(self._inbox_item(question, cui, f"/triage/{batch_id}/resume"))
        for graph, cfg, path in (
            (self.reconcile, self._recon_cfg(cui, period), f"/recon/{cui}/{period}/resume"),
            (self.close, self._close_cfg(cui, period), f"/close/{cui}/{period}/resume"),
        ):
            question = self._waiting(graph, cfg)
            if question is not None:
                items.append(self._inbox_item(question, cui, path))
        items = [i for i in items if i["actor"] in ("accountant", None)]
        return {"cui": cui, "period": period, "items": items}

    def _inbox_item(
        self, question: dict[str, Any] | None, cui: str, path: str, job: Any = None
    ) -> dict[str, Any]:
        kind = question.get("kind") if question else None
        row = self.catalog.hitl.get(kind) if kind else None
        return {
            "kind": kind,
            "actor": row.get("actor") if row else None,
            "answer_schema": row.get("resume_schema") if row else None,
            "answer_path": path if question else None,
            "question": question,
            "explanation": self.gateway.explanation(question, cui) if question else None,
            "job": (
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "articol_id": job.articol_id,
                    "period": job.period,
                    "error": job.error,
                }
                if job is not None
                else None
            ),
        }

    # -- the answer log (WP-33) --

    @staticmethod
    def _start(graph: Any, cfg: dict, inputs: dict[str, Any]) -> None:
        """Start a run, or go on with one already there: a run waiting on a person is left
        as it is; a run stopped between nodes (the process died mid-run, WP-65) continues
        from its last checkpoint instead of looking like a question that never comes."""
        state = graph.get_state(cfg)
        if any(t.interrupts for t in state.tasks):
            return
        graph.invoke(None if state.next else inputs, cfg)

    @staticmethod
    def _waiting(graph: Any, cfg: dict) -> dict[str, Any] | None:
        tasks = graph.get_state(cfg).tasks
        return next((i.value for t in tasks for i in t.interrupts), None)

    def _answer(
        self,
        graph: Any,
        cfg: dict,
        graph_id: str,
        cui: str | None,
        payload: Any,
        operator: str | None,
    ) -> None:
        """Resume *graph* with a person's answer and log it, whatever became of it.

        With no question waiting the graph is not touched: an answer to nothing changes
        nothing (it is logged as ``no_question``).
        """
        before = self._waiting(graph, cfg)
        if before is not None:
            graph.invoke(Command(resume=payload), cfg)
        self.answers.add(
            record_answer(
                graph_id=graph_id,
                thread_id=cfg["configurable"]["thread_id"],
                tenant_cui=cui,
                before=before,
                after=self._waiting(graph, cfg),
                answer=payload,
                operator=operator,
            )
        )

    # -- reconcile_sink (WP-23) --

    def recon_waiting(self, cui: str, period: str) -> list[WaitingJob]:
        """The period's jobs whose ingest thread ended at an undecided PRE check."""
        out = []
        for job in self.jobs.for_period(cui, period):
            if job.status != "needs_human":
                continue
            state = self.ingest.get_state(self._cfg(job.job_id))
            pre = state.values.get("pre") or {}
            if state.tasks or state.values.get("status") != "needs_human":
                continue
            if pre.get("verdict") != "ambiguous" or "canonical" not in state.values:
                continue
            source = self.catalog.source_docs.get(state.values.get("source_doc_id")) or {}
            out.append(
                WaitingJob(
                    job=job,
                    doc=CanonicalDocument.model_validate(state.values["canonical"]),
                    fiscal_class=source.get("fiscal_class"),
                    axes=dict(state.values.get("axes") or {}),
                )
            )
        return sorted(out, key=lambda w: (w.doc.date, w.job.job_id))

    def _thread_job(self, job: JobRecord) -> WaitingJob | None:
        values = self.ingest.get_state(self._cfg(job.job_id)).values
        if "canonical" not in values:
            return None
        source = self.catalog.source_docs.get(values.get("source_doc_id")) or {}
        return WaitingJob(
            job=job,
            doc=CanonicalDocument.model_validate(values["canonical"]),
            fiscal_class=source.get("fiscal_class"),
            axes=dict(values.get("axes") or {}),
        )

    def post_waiting(self, cui: str, period: str) -> list[WaitingJob]:
        """The period's acked jobs: SAGA shows them validated, POST checks how (WP-27)."""
        out = [
            w
            for job in self.jobs.for_period(cui, period)
            if job.status == "acked" and (w := self._thread_job(job)) is not None
        ]
        return sorted(out, key=lambda w: (w.doc.date, w.job.job_id))

    def post_check(self, w: WaitingJob) -> PostResult:
        profile = pre_profile(
            self.catalog, w.doc, fiscal_class=w.fiscal_class, axes=w.axes, stage="post"
        )
        articol = self.catalog.articole.get(w.job.articol_id or "") or {}
        eye = rj_eye(self.registry, self.blobs, w.job.tenant.cui)
        return how_check(w.doc, articol, profile, eye, w.job.tenant.cui)

    def _post_known(self, job_id: str, snapshot_id: str) -> bool:
        if self.recon is None:
            return False
        return any(
            self.recon.get(job_id, "post", sid) is not None
            for sid in (snapshot_id, f"{snapshot_id}:person")
        )

    def _settle_post(self, w: WaitingJob, result: PostResult) -> None:
        if self.recon is not None:
            self.recon.put_once(w.job.job_id, "post", result)

    def post_open(self, cui: str, period: str) -> list[str]:
        """Acked jobs whose posting is not settled: unchecked (no journal), an unanswered
        mismatch, or a requested storno SAGA does not show yet."""
        out = []
        for w in self.post_waiting(cui, period):
            res = self.post_check(w)
            if res.verdict == "how_ok":
                continue
            answer = (
                self.recon.get(w.job.job_id, "post", f"{res.snapshot_id}:person")
                if self.recon is not None and res.verdict == "how_mismatch"
                else None
            )
            if answer is None or str(answer.get("reason", "")).startswith("person: storno"):
                out.append(w.job.job_id)
        return out

    def _settle_pre(self, w: WaitingJob, result: PreResult) -> None:
        """Hand a final PRE verdict back to the job's own thread (glue = job id)."""
        if self.recon is not None:
            result = self.recon.put_once(w.job.job_id, "pre", result)
        cfg = self._cfg(w.job.job_id)
        if result.verdict == "already_posted":
            self.jobs.update(w.job.job_id, status="already_in_sink", error=None)
            self.ingest.update_state(
                cfg,
                {"status": "already_in_sink", "pre": result.model_dump()},
                as_node="reconcile_pre",
            )
            return
        if result.verdict != "absent":
            raise ValueError(f"only a decided verdict is handed back, not {result.verdict!r}")
        self.jobs.update(w.job.job_id, status="reconcile_pre", error=None)
        self.ingest.update_state(
            cfg, {"status": "reconcile_pre", "pre": result.model_dump()}, as_node="reconcile_pre"
        )
        self.ingest.invoke(None, cfg)  # judge → v3_approve, as if PRE had said absent

    def _rj_export_months(self, cui: str, export_id: str) -> list[str] | None:
        row = self.registry.latest_export(cui, "rj")
        return list(row.periods) if row is not None and row.export_id == export_id else None

    @staticmethod
    def _recon_cfg(cui: str, period: str) -> dict:
        return {"configurable": {"thread_id": f"recon:{cui}:{period}"}}

    def recon_view(self, cui: str, period: str) -> dict[str, Any]:
        state = self.reconcile.get_state(self._recon_cfg(cui, period))
        question = next((i.value for t in state.tasks for i in t.interrupts), None)
        return {
            "question": question,
            "explanation": self.gateway.explanation(question, cui),
            "settled": state.values.get("settled") or [],
            "waiting": [w.job.job_id for w in self.recon_waiting(cui, period)],
            "post_open": self.post_open(cui, period),
        }

    def start_recon(self, cui: str, period: str) -> dict[str, Any]:
        """One pass over the period's PRE questions; a waiting question is shown, not redone."""
        if self.registry.tenant(cui) is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        cfg = self._recon_cfg(cui, period)
        self._start(self.reconcile, cfg, {"cui": cui, "period": period, "settled": []})
        return self.recon_view(cui, period)

    def resume_recon(
        self, cui: str, period: str, payload: Any, operator: str | None = None
    ) -> dict[str, Any]:
        cfg = self._recon_cfg(cui, period)
        self._answer(self.reconcile, cfg, "reconcile_sink", cui, payload, operator)
        return self.recon_view(cui, period)

    # -- period --

    def expected(self, cui: str, period: str) -> list[ExpectedJob]:
        """The month's jobs with the documents their threads carry."""
        out = []
        for job in self.jobs.for_period(cui, period):
            values = self.ingest.get_state(self._cfg(job.job_id)).values
            if "canonical" in values:
                doc = CanonicalDocument.model_validate(values["canonical"])
                out.append(ExpectedJob(job=job, doc=doc))
        return out

    def prior(self, cui: str, period: str) -> list[ExpectedJob]:
        """The two months before *period*: invoices a bank line of this month may settle."""
        return [ej for p in _months_back(period, SETTLE_MONTHS)[1:] for ej in self.expected(cui, p)]

    def stalled(self, cui: str, period: str) -> list[str]:
        """The month's jobs minted with no document on their thread (never started): the
        close counts them as outbound holes (WP-73 G2)."""
        return [
            job.job_id
            for job in self.jobs.for_period(cui, period)
            if job.status != "rejected"
            and "canonical" not in self.ingest.get_state(self._cfg(job.job_id)).values
        ]

    def settlement(self, line: CanonicalDocument) -> SettlementProposal:
        """The invoices an unbound bank line could settle (WP-22, WP-30), from this tenant's
        invoice Jobs and the books' journals in the line's month and the two before it, less
        what other bound bank lines already paid on each."""
        cui = line.tenant.cui
        periods = _months_back(line.period, SETTLE_MONTHS)
        jobs = [ej for p in periods for ej in self.expected(cui, p)]
        invoices = [
            InvoiceJob(job_id=ej.job.job_id, doc=ej.doc)
            for ej in jobs
            if ej.doc.doc_class in SETTLES.values() and ej.job.status not in ("rejected", "failed")
        ]
        books = []
        for p in periods:
            eye = self._eye(cui, p)
            if eye.covers(cui, p):
                books.extend(eye.documents(cui, p))
        bound = [
            ej.doc
            for ej in jobs
            if ej.doc.doc_class in SETTLES
            and ej.doc.job_id != line.job_id
            and ej.doc.partner.cui
            and ej.job.status not in ("rejected", "failed")
        ]
        paid: dict[tuple[str, str], Decimal] = {}  # what bound lines paid per invoice (WP-30)
        for d in bound:
            if d.maps.get("factura_numar"):
                key = settle_key(d.partner.cui, d.maps["factura_numar"])
                paid[key] = paid.get(key, Decimal(0)) + Decimal(d.totals.gross)
        return propose_settlement(line, invoices, books, paid=paid)

    def _eye(self, cui: str, period: str):
        probe = JobRecord(
            job_id="period",
            tenant=TenantRef(cui=cui, saga_firm_folder="-"),
            period=period,
            status="bound",
        )
        return witnesses_provider(self.registry, self.blobs)(probe).eye

    # -- CO.DiT --

    def axes(self, cui: str, period: str, fallback: dict[str, str] | None = None) -> dict:
        """The period's CO.DiT axes; *fallback* (explicit operator input) only without one."""
        doc = self.codits.get(cui, period) if self.codits is not None else None
        return doc.derive() if doc is not None else dict(fallback or {})

    def put_codit(self, cui: str, period: str, data: CoditInput) -> Codit:
        if self.codits is None:
            raise IngestRefused("CO.DiT store not wired")
        if self.registry.tenant(cui) is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        previous = self.codits.get(cui, period)
        run = self.closes.get(cui, period) if self.closes is not None else None
        closed = run is not None and run.status in ("filed", "v4_done")
        if closed and previous is not None:
            raise IngestRefused(f"{period} is filed; a filed period's CO.DiT is not rewritten")
        doc = write_codit(self.catalog, cui, period, data, previous=previous, closed=closed)
        self.codits.put(doc)
        return doc

    # -- bank statements (WP-13) --

    def read_statement(
        self,
        tenant: Tenant,
        period: str,
        pdf: bytes,
        meta: StatementMeta | None = None,
        strong: bool = False,
    ) -> tuple[Extraction, str]:
        """The extract contract for a statement PDF (WP-21): read once per
        ``(source_hash, document_ai)``, reused after; returns it with the PDF's bucket key.

        Gemini (00_LAW §8 A4): a read that fails the statement checks against *meta* is read
        once more by the strong tier; a read that still fails is refused and never stored."""
        cui = tenant.cui
        source_hash = hashlib.sha256(pdf).hexdigest()
        for backend in ("document_ai", "gemini"):
            row = self.extracts.get(source_hash, backend)
            if row is None:
                continue
            if not str(row["prefix"]).startswith(f"tenants/{cui}/"):
                raise IngestRefused("this PDF was read for another tenant")
            return read_extraction(self.blobs, row["prefix"]), f"{row['prefix']}/statement.pdf"
        reader = self.reader_for(cui)
        if reader is None:
            raise IngestRefused(
                "no statement reader is wired (DOCUMENT_AI_PROCESSOR, or Gemini for synthetic"
                " tenants with MODEL_CALLS=live): send the extract tables"
            )
        try:
            if reader is self.gemini_reader and meta is not None:
                extraction = self._read_until_it_ties(reader, pdf, meta, cui, strong)
            else:
                extraction = reader(pdf, tenant_cui=cui)
        except OutOfQuota as exc:
            raise ReadingDeferred(str(exc), exc.retry_after) from exc
        except (DocumentAiError, GeminiError) as exc:
            raise IngestRefused(str(exc)) from exc
        prefix = f"tenants/{cui}/{tenant.punct}/{period}/extras/source/{source_hash}"
        self.blobs.put(f"{prefix}/statement.pdf", pdf)
        write_extraction(self.blobs, prefix, extraction)
        self.extracts.put(extraction.meta, prefix)  # the row after the files it proves
        return extraction, f"{prefix}/statement.pdf"

    def _read_until_it_ties(
        self, reader: Any, pdf: bytes, meta: StatementMeta, cui: str, strong: bool
    ) -> Extraction:
        """Gemini's read; a second run on the strong tier when the first does not confirm."""
        extraction, _, model = reader.read_with_model(pdf, tenant_cui=cui, strong=strong)
        problem = statement_problem(extraction, meta, cui)
        if problem is None:
            return extraction
        if reader.role.tiers is None or reader.is_strong(model):
            raise IngestRefused(f"{problem} (read by {model})")
        extraction, _, again = reader.read_with_model(pdf, tenant_cui=cui, escalate=True)
        second = statement_problem(extraction, meta, cui)
        if second is not None:
            raise IngestRefused(f"{second} (read by {model}, then {again})")
        return extraction

    def _observe_reading(self, cui: str, pdf: bytes, meta: StatementMeta) -> None:
        """Where the reader is not called: what Gemini would be given (the file by
        fingerprint, never its bytes)."""
        self.gateway.observe(
            "ocr_extract",
            {
                "tenant_cui": cui,
                "file": {
                    "sha256": hashlib.sha256(pdf).hexdigest(),
                    "bytes": len(pdf),
                    "content_type": "application/pdf",
                },
                "header": meta.model_dump(),
            },
            cui,
        )

    def reader_for(self, cui: str) -> Any:
        """Who reads this tenant's statement PDFs: Gemini direct for a synthetic tenant when
        it is wired (WP-36), else Document AI; never Gemini for a client tenant."""
        if self.gemini_reader is not None and self._synthetic(cui):
            return self.gemini_reader
        return self.statement_reader

    def ocr_eval(self, cui: str, case: str | None, model: str | None) -> dict[str, Any]:
        """WP-37: read the evaluation's synthetic statements with Gemini and score them.

        Synthetic tenants only; nothing is minted or stored but the model-call records.
        *model* reads with another Google AI Studio model, for comparison only.
        """
        from dataclasses import replace

        from poarta_contabila.model_roles import ai_studio_model_ok
        from poarta_contabila.ocr_eval import cases, score, summary

        if not self._synthetic(cui):
            raise IngestRefused(f"tenant {cui} is not a registered synthetic tenant")
        if self.gemini_reader is None:
            raise IngestRefused("the Gemini reader is not wired (MODEL_CALLS=live and the key)")
        reader = self.gemini_reader
        if model:
            if not ai_studio_model_ok(model):
                raise IngestRefused(f"{model!r} is not a Google AI Studio model id (gemini-…)")
            limits = {**reader.role.rate_limits}
            limits.setdefault(model, reader.role.rate_limits[str(reader.role.model)])
            reader = replace(
                reader, role=reader.role.model_copy(update={"model": model, "rate_limits": limits})
            )
        # the evaluation scores one model: never another tier (00_LAW §8 A4)
        reader = replace(reader, role=reader.role.model_copy(update={"tiers": None}))
        chosen = [c for c in cases() if case is None or c.name == case]
        if not chosen:
            raise IngestRefused(f"unknown case {case!r}")
        scores = [score(c, reader, cui) for c in chosen]
        return {
            "scores": [s.model_dump() for s in scores],
            "summary": summary(scores),
        }

    def ingest_statement(
        self,
        cui: str,
        meta: StatementMeta,
        tables: list[dict[str, Any]] | None,
        pdf: bytes,
        strong: bool = False,
    ) -> dict[str, Any]:
        """A PDF statement → a pack and one Job per movement line; or, when no model can read
        it now, ``{"status": "waiting", …}``: parked and read again later (WP-42)."""
        self._sync_reserve()
        try:
            return self._ingest_statement(cui, meta, tables, pdf, strong)
        except ReadingDeferred as exc:
            return self._park(cui, meta, pdf, strong, exc)

    def _park(
        self, cui: str, meta: StatementMeta, pdf: bytes, strong: bool, exc: ReadingDeferred
    ) -> dict[str, Any]:
        tenant = self.registry.tenant(cui)
        sha = hashlib.sha256(pdf).hexdigest()
        key = f"tenants/{cui}/{tenant.punct}/{meta.statement_date[:7]}/extras/waiting/{sha}.pdf"
        self.blobs.put(key, pdf)
        now = datetime.now(UTC)
        wait = self.reading_waits.put(
            ReadingWait(
                wait_id=f"{cui}:{sha}",
                tenant_cui=cui,
                meta=meta.model_dump(mode="json"),
                pdf_key=key,
                strong=strong,
                reason=exc.reason,
                not_before=(now + timedelta(seconds=exc.retry_after)).isoformat(),
                created_at=now.isoformat(),
            )
        )
        out = {"status": "waiting", **wait.model_dump(include={"wait_id", "not_before", "reason"})}
        ask = self._reading_question()
        return {**out, "ask": ask} if ask else out

    # -- WP-43: the operator's choice when every tier is spent (00_LAW §8 A6) --

    def _sync_reserve(self) -> None:
        """The Gemini reader reads with the reserve models while today's choice says so."""
        reader = self.gemini_reader
        if reader is None or reader.role.tiers is None or not reader.role.tiers.reserve:
            return
        latest = self.reading_choices.latest(reader.limiter.today())
        on = latest is not None and latest.choice == "reserve"
        reader.reserve_until = datetime.fromisoformat(latest.until) if on else None

    def _reading_question(self) -> dict[str, Any] | None:
        """The question for a person, when statements wait and the reserve is not open."""
        reader = self.gemini_reader
        if reader is None or reader.role.tiers is None or reader.reserve_active():
            return None
        reserve = list(reader.role.tiers.reserve)
        options = {
            "wait": "read the waiting statements after Pacific midnight, when the quotas reset",
            "skip": "set one waiting statement aside (POST …/waiting/{wait_id}/skip) and send"
            " its tables with the upload instead",
        }
        if reserve:
            options["reserve"] = f"read with the reserve models until Pacific midnight: {reserve}"
        return {
            "question": "Every model the catalog reads with now is spent or busy. What next?",
            "options": options,
            "answer_at": "POST /reading/{cui}/choice {choice: wait | reserve}",
        }

    def reading_choose(self, cui: str, choice: str, operator: str | None) -> dict[str, Any]:
        """Record today's choice; ``reserve`` opens the reserve models until Pacific midnight
        and sends this tenant's waiting statements to be read again now."""
        reader = self.gemini_reader
        if reader is None:
            raise IngestRefused("the Gemini reader is not wired (MODEL_CALLS=live and the key)")
        if choice not in ("wait", "reserve"):
            raise IngestRefused("choice is wait or reserve")
        if choice == "reserve" and not (reader.role.tiers and reader.role.tiers.reserve):
            raise IngestRefused("the catalog lists no reserve models")
        now = datetime.now(UTC)
        released = 0
        if choice == "reserve":
            for wait in self.reading_waits.list(cui, "waiting"):
                self.reading_waits.update(wait.model_copy(update={"not_before": now.isoformat()}))
                released += 1
        day = reader.limiter.today()
        record = ReadingChoice(
            choice_id=f"{day}:{uuid.uuid4().hex[:12]}",
            day=day,
            choice=choice,
            tenant_cui=cui,
            operator=operator,
            at=now.isoformat(),
            until=reader.limiter.midnight().astimezone(UTC).isoformat(),
            released=released,
        )
        self.reading_choices.add(record)
        self._sync_reserve()
        read = self.retry_waiting(cui, now) if released else []
        return {"choice": record.model_dump(mode="json"), "read": read}

    def skip_waiting(
        self, cui: str, wait_id: str, reason: str, operator: str | None
    ) -> dict[str, Any]:
        """Set a parked statement aside: it is never read by a model (send its tables)."""
        found = [w for w in self.reading_waits.list(cui, "waiting") if w.wait_id == wait_id]
        if not found:
            raise IngestRefused(f"no statement of {cui} waits as {wait_id}")
        done = found[0].model_copy(
            update={"status": "skipped", "reason": reason or "set aside", "skipped_by": operator}
        )
        self.reading_waits.update(done)
        return done.model_dump(mode="json", exclude={"meta"})

    def retry_waiting(self, cui: str | None = None, now: datetime | None = None) -> list[dict]:
        """Read again every parked statement whose time has come (WP-42): minted when the read
        confirms, parked again when no model can read yet, refused otherwise."""
        now = now or datetime.now(UTC)
        self._sync_reserve()
        out = []
        for wait in self.reading_waits.due(now):
            if cui is not None and wait.tenant_cui != cui:
                continue
            meta = StatementMeta.model_validate(wait.meta)
            update: dict[str, Any] = {"attempts": wait.attempts + 1}
            try:
                pdf = self.blobs.get(wait.pdf_key)
                result = self._ingest_statement(wait.tenant_cui, meta, None, pdf, wait.strong)
                update |= {"status": "read", "result": result, "reason": "read"}
            except ReadingDeferred as exc:
                later = now + timedelta(seconds=exc.retry_after)
                update |= {"reason": exc.reason, "not_before": later.isoformat()}
            except IngestRefused as exc:
                update |= {"status": "refused", "reason": str(exc)}
            done = wait.model_copy(update=update)
            self.reading_waits.update(done)
            out.append(done.model_dump(mode="json", exclude={"meta"}))
        return out

    def reading_budget(self, cui: str, documents: int = 0) -> dict[str, Any]:
        """WP-42: what the Gemini reader may still send today, what waits, and — for a batch
        of *documents* about to be uploaded — whether today's budget covers it."""
        reader = self.gemini_reader
        if reader is None:
            raise IngestRefused("the Gemini reader is not wired (MODEL_CALLS=live and the key)")
        self._sync_reserve()
        models = reader.budget()
        waiting = self.reading_waits.list(cui, "waiting")

        def left(tier: str) -> int | None:
            rows = [m["left_today"] for m in models if m["tier"] == tier]
            return None if any(v is None for v in rows) else sum(rows)

        everyday, strong = left("everyday"), left("strong")
        need = documents + len(waiting)
        warnings = []
        if everyday is not None and need > everyday:
            warnings.append(
                f"{need} statements to read, {everyday} everyday reads left today:"
                " the rest wait until Pacific midnight (or use the strong tier)"
            )
        if strong is not None and strong < need:
            warnings.append(
                f"{strong} strong reads left today: a second run for more than {strong}"
                " statements waits until Pacific midnight"
            )
        return {
            "models": models,
            "everyday_left": everyday,
            "strong_left": strong,
            "resets_in_seconds": round(reader.limiter.to_midnight()),
            "waiting": [w.model_dump(mode="json", exclude={"meta"}) for w in waiting],
            "documents": documents,
            "warnings": warnings,
            "reserve_open_until": (
                reader.reserve_until.isoformat() if reader.reserve_active() else None
            ),
            "choices_today": [
                c.model_dump(mode="json")
                for c in self.reading_choices.recent()
                if c.day == reader.limiter.today()
            ],
            "ask": self._reading_question() if waiting else None,
        }

    def _ingest_statement(
        self,
        cui: str,
        meta: StatementMeta,
        tables: list[dict[str, Any]] | None,
        pdf: bytes,
        strong: bool = False,
    ) -> dict[str, Any]:
        """A PDF statement → a pack and one Job per movement line.

        *strong*: Gemini reads with its strong tier first (00_LAW §8 A4).

        The movement tables come with the upload or, when none are sent, from the statement
        reader (Document AI), which must also show the tenant's CUI and the header's IBAN.
        """
        tenant: Tenant | None = self.registry.tenant(cui)
        if tenant is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        if not pdf.startswith(b"%PDF"):
            raise IngestRefused("the statement source must be the bank's PDF")
        period = meta.statement_date[:7]
        pdf_key = None
        if tables is not None or self.reader_for(cui) is not self.gemini_reader:
            self._observe_reading(cui, pdf, meta)
        if tables is None:
            extraction, pdf_key = self.read_statement(tenant, period, pdf, meta, strong)
            problem = statement_problem(extraction, meta, cui, tie=False)
            if problem is not None:
                raise IngestRefused(problem)
            tables = extraction.tables
        try:
            statement = parse_statement(tables, meta, cui)
        except StatementError as exc:
            raise IngestRefused(str(exc)) from exc
        base = f"tenants/{cui}/{tenant.punct}/{period}/extras/{statement.statement_id}"
        if pdf_key is None:
            pdf_key = f"{base}/statement.pdf"
            self.blobs.put(pdf_key, pdf)
        self.blobs.put(f"{base}/statement.json", statement.model_dump_json().encode())
        jobs = []
        for line in statement.lines:
            source_hash = line_source_hash(statement.statement_id, line.seq)
            pack = Pack(
                tenant_cui=cui,
                saga_firm_folder=tenant.saga_firm_folder,
                punct=tenant.punct,
                period=line.date[:7],
                source_hash=source_hash,
                source_doc_id="extras_statement_pdf",
                kinds=["pdf"],
                our_role="n/a",
                identity_ok=True,  # the holder CUI was checked against the tenant
            )
            decision = decide_emit(self.catalog, pack)
            if not decision.emit:
                raise IngestRefused(f"line {line.seq}: emit gates failed: {decision.failed}")
            result = self.jobs.emit(pack, decision)
            if result.created:
                doc = statement_line_document(
                    statement, line, job=result.job, bucket_key=pdf_key, source_hash=source_hash
                )
                self.ingest.invoke(
                    start_payload(
                        result.job,
                        doc,
                        source_doc_id="extras_statement_pdf",
                        axes=self.axes(cui, doc.period),
                    ),
                    self._cfg(result.job.job_id),
                )
            jobs.append(
                {"seq": line.seq, "created": result.created, **self.view(result.job.job_id)}
            )
        return {"statement_id": statement.statement_id, "lines": len(statement.lines), "jobs": jobs}

    # -- filings --

    def open_filings(self, cui: str, period: str) -> list[dict[str, Any]]:
        """Open the items the period's CO.DiT makes due (idempotent) and list them."""
        if self.filings is None:
            raise IngestRefused("filing store not wired")
        doc = self.codits.get(cui, period) if self.codits is not None else None
        if doc is None:
            raise IngestRefused(f"no CO.DiT for {period}: nothing is assumed due")
        for row in due_filings(self.catalog, doc.derive()):
            self.filings.open(cui, period, row["filing_id"])
        return self.filings_view(cui, period)

    def filings_view(self, cui: str, period: str) -> list[dict[str, Any]]:
        if self.filings is None:
            raise IngestRefused("filing store not wired")
        items = self.filings.items(cui, period)
        controls = (
            {c["control_id"]: c["status"] for c in self.period_diff(cui, period)["controls"]}
            if items
            else {}
        )
        return [v.model_dump() for v in filing_views(self.catalog, cui, period, items, controls)]

    def filing_receipt(
        self, cui: str, period: str, filing_id: str, data: bytes, filename: str, by: str
    ) -> list[dict[str, Any]]:
        """Store the receipt artefact (the only thing that closes an item)."""
        if self.filings is None:
            raise IngestRefused("filing store not wired")
        if filing_id not in self.filings.items(cui, period):
            raise IngestRefused(f"{filing_id} is not due for {period}; open the period's items")
        if not data:
            raise IngestRefused("a receipt is a file; an empty upload closes nothing")
        tenant = self.registry.tenant(cui)
        digest = hashlib.sha256(data).hexdigest()
        key = (
            f"tenants/{cui}/{tenant.punct if tenant else 'default'}/{period}/receipts/"
            f"{filing_id}/{digest}{Path(filename).suffix.lower()}"
        )
        self.blobs.put(key, data)
        self.filings.receipt(cui, period, filing_id, key, by)
        return self.filings_view(cui, period)

    # -- close --

    @staticmethod
    def _close_cfg(cui: str, period: str) -> dict:
        return {"configurable": {"thread_id": f"close:{cui}:{period}"}}

    def close_view(self, cui: str, period: str) -> dict[str, Any]:
        state = self.close.get_state(self._close_cfg(cui, period))
        question = next((i.value for t in state.tasks for i in t.interrupts), None)
        stored = self.closes.get(cui, period)
        return {
            "run": stored.model_dump() if stored else None,
            "question": question,
            "explanation": self.gateway.explanation(question, cui),
        }

    def start_close(self, cui: str, period: str, axes: dict[str, str]) -> dict[str, Any]:
        cfg = self._close_cfg(cui, period)
        self._start(self.close, cfg, {"cui": cui, "period": period, "axes": axes})
        return self.close_view(cui, period)

    def resume_close(
        self, cui: str, period: str, payload: Any, operator: str | None = None
    ) -> dict[str, Any]:
        cfg = self._close_cfg(cui, period)
        self._answer(self.close, cfg, "monthly_close", cui, payload, operator)
        return self.close_view(cui, period)

    def period_diff(
        self, cui: str, period: str, axes: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Layer 1 for one firm-month: PeriodDiff, control runs, and whether V2 may file."""
        expected = self.expected(cui, period)
        eye = self._eye(cui, period)
        axes = self.axes(cui, period, axes)
        rules = self.rules.active(cui) if self.rules is not None else []
        diff, runs = build_period_diff(
            self.catalog,
            cui,
            period,
            expected,
            eye,
            axes=axes,
            rules=rules,
            stalled=self.stalled(cui, period),
            prior=self.prior(cui, period),
        )
        if self.periods is not None:
            self.periods.save(diff, runs)
        return {
            "diff": diff.model_dump(),
            "controls": [r.model_dump() for r in runs],
            "can_file": can_file(diff),
        }

    # -- uploads --

    def put_export(
        self,
        cui: str,
        kind: ExportKind,
        product: Product | None,
        data: bytes,
        filename: str,
        periods: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.registry.tenant(cui) is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        covered = check_export(cui, product, kind, data, filename, periods)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        row = export_row(cui, product, kind, data, filename, covered, now)
        self.blobs.put(row.bucket_key, data)
        self.registry.add_export(row)
        return row.model_dump()

    # -- folder_triage: expense reports (WP-28) --

    _DECONT_KINDS = {".pdf": "pdf", ".xls": "xls", ".xlsx": "xlsx", ".msg": "msg", ".eml": "eml"}

    @staticmethod
    def _batch_cfg(batch_id: str) -> dict:
        return {"configurable": {"thread_id": f"batch:{batch_id}"}}

    def batch_tenant(self, batch_id: str) -> str | None:
        """The tenant a triage batch belongs to; None for an unknown batch."""
        values = self.triage.get_state(self._batch_cfg(batch_id)).values
        return (values.get("pack") or {}).get("tenant_cui") if values else None

    def batch_view(self, batch_id: str) -> dict[str, Any]:
        state = self.triage.get_state(self._batch_cfg(batch_id))
        if not state.values:
            raise KeyError(batch_id)
        question = next((i.value for t in state.tasks for i in t.interrupts), None)
        values = state.values
        return {
            "batch_id": batch_id,
            "question": question,
            "decision": values.get("decision"),
            "children": [
                {
                    "source_doc_id": c["pack"]["source_doc_id"],
                    "part_hash": c["pack"]["source_hash"],
                    "emit": c["decision"]["emit"],
                    "failed": c["decision"]["failed"],
                    "job_id": c.get("job_id"),
                }
                for c in values.get("children") or []
            ],
        }

    def ingest_decont(
        self, cui: str, data: bytes, filename: str, period: str, *, tenant_on_doc: bool
    ) -> dict[str, Any]:
        """An expense report (decont de cheltuieli, A2) → folder_triage on ``batch:decont-…``.

        The report is a container: it never becomes a Job. Once its identity and primary
        gates pass, a person names its parts (``decont_split``); each part is a child Pack
        through the same gates. Nothing reads the file yet, so the tenant's presence on it
        is the operator's statement (``tenant_on_doc``); without it the identity gate fails.
        """
        tenant: Tenant | None = self.registry.tenant(cui)
        if tenant is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        kind = self._DECONT_KINDS.get(Path(filename).suffix.lower())
        if kind is None:
            raise IngestRefused(f"an expense report is one of {sorted(self._DECONT_KINDS)}")
        if not data:
            raise IngestRefused("the expense report file is empty")
        source_hash = hashlib.sha256(data).hexdigest()
        batch_id = f"decont-{cui}-{source_hash[:32]}"
        cfg = self._batch_cfg(batch_id)
        self.batches.add(cui, batch_id, period)  # a report uploaded again is listed too
        if self.triage.get_state(cfg).values:
            return {"created": False, **self.batch_view(batch_id)}
        self.blobs.put(
            f"tenants/{cui}/{tenant.punct}/{period}/decont/source/{source_hash}/{filename}", data
        )
        row = self.catalog.source_docs["decont_cheltuieli"]
        self.gateway.observe(  # shadow: what Gemini would be given to propose the parts
            "ocr_decont_split",
            {
                "tenant_cui": cui,
                "file": {"sha256": source_hash, "bytes": len(data), "kind": kind},
                "children": list(row["split"]["children"]),
            },
            cui,
        )
        pack = Pack(
            tenant_cui=cui,
            saga_firm_folder=tenant.saga_firm_folder,
            punct=tenant.punct,
            period=period,
            source_hash=source_hash,
            source_doc_id="decont_cheltuieli",
            kinds=[kind],
            our_role="inbound",
            identity_ok=tenant_on_doc,
        )
        self.triage.invoke({"pack": pack.model_dump()}, cfg)
        return {"created": True, **self.batch_view(batch_id)}

    def resume_batch(
        self, batch_id: str, payload: Any, operator: str | None = None
    ) -> dict[str, Any]:
        self.batch_view(batch_id)  # KeyError for an unknown batch
        cfg = self._batch_cfg(batch_id)
        cui = (self.triage.get_state(cfg).values.get("pack") or {}).get("tenant_cui")
        self._answer(self.triage, cfg, "folder_triage", cui, payload, operator)
        return self.batch_view(batch_id)

    def ingest_upload(self, cui: str, data: bytes, filename: str) -> dict[str, Any]:
        """XML first: an SPV zip or a UBL XML becomes a Job and starts its thread."""
        tenant: Tenant | None = self.registry.tenant(cui)
        if tenant is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        try:
            if zipfile.is_zipfile(io.BytesIO(data)):
                xml = read_spv_zip(data).invoice
            elif filename.lower().endswith(".xml"):
                xml = data
            else:
                raise IngestRefused("v1 ingests SPV zips and UBL XML only (XML first)")
            invoice = parse_ubl(xml, where=filename)
            source_hash = hashlib.sha256(data).hexdigest()
            draft_job = JobRecord(
                job_id="pending", tenant=tenant.ref(), period="2000-01", status="ingested"
            )
            source = SourceRef(
                kind="ubl_spv",
                bucket_key=f"tenants/{cui}/{tenant.punct}/{invoice.issue_date[:7]}/source/"
                f"{source_hash}/{filename}",
                content_type="application/zip" if xml is not data else "application/xml",
                source_hash=source_hash,
            )
            doc = to_canonical(invoice, job=draft_job, source=source)
        except UblError as exc:
            raise IngestRefused(str(exc)) from exc
        # WP-73 G1: a counterparty without a RO CUI, from abroad, is an invoice from abroad
        other = (
            invoice.customer if doc.doc_class in ("iesire", "storn_iesire") else invoice.supplier
        )
        source_doc_id = (
            "foreign_invoice_xml"
            if other.cui is None and (other.country or "RO").upper() != "RO"
            else "ro_efactura_ubl"
        )
        self.gateway.observe(  # shadow: what Jev would be asked at triage
            "jev_source_doc",
            {
                "tenant_cui": cui,
                "filename": filename,
                "content_type": source.content_type,
                "root": invoice.root,
                "type_code": invoice.type_code,
            },
            cui,
        )
        self.gateway.observe(
            "jev_our_role",
            {
                "tenant_cui": cui,
                "supplier": invoice.supplier.model_dump(),
                "customer": invoice.customer.model_dump(),
            },
            cui,
        )

        pack = Pack(
            tenant_cui=cui,
            saga_firm_folder=tenant.saga_firm_folder,
            punct=tenant.punct,
            period=doc.period,
            source_hash=source_hash,
            source_doc_id=source_doc_id,
            kinds=["ubl_spv"] if source_doc_id == "ro_efactura_ubl" else ["xml"],
            our_role="outbound" if doc.doc_class in ("iesire", "storn_iesire") else "inbound",
            counterparty_cui=doc.partner.cui,
            identity_ok=True,
            is_storno=doc.is_storno,
        )
        decision = decide_emit(self.catalog, pack)
        if not decision.emit:
            raise IngestRefused(f"emit gates failed: {decision.failed}")
        result = self.jobs.emit(pack, decision)
        started = "canonical" in self.ingest.get_state(self._cfg(result.job.job_id)).values
        if not result.created and started:
            return {"created": False, **self.view(result.job.job_id)}
        # a Job minted by folder_triage (an expense report's part) gets its thread now
        self.blobs.put(source.bucket_key, data)
        doc = doc.model_copy(update={"job_id": result.job.job_id})
        self.ingest.invoke(
            start_payload(
                result.job,
                doc,
                source_doc_id=source_doc_id,
                axes=self.axes(cui, doc.period),
            ),
            self._cfg(result.job.job_id),
        )
        return {"created": result.created, **self.view(result.job.job_id)}


def build_runtime(**parts: Any) -> Runtime:
    return Runtime(**parts)


def runtime_from_env(catalog: Catalog, dsn: str | None) -> tuple[Runtime | None, str]:
    """The production runtime, or None with the reason it is not wired."""
    from poarta_contabila.storage import S3BlobStore, S3Config

    if not dsn:
        return None, "DATABASE_URL not set"
    s3 = S3Config.from_env()
    if s3 is None:
        return None, "S3_ENDPOINT / S3_ACCESS_KEY / S3_SECRET_KEY / S3_BUCKET not set"
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from poarta_contabila.agent import PostgresAgentStore
    from poarta_contabila.answers import PostgresAnswerLog
    from poarta_contabila.close import PostgresCloseStore
    from poarta_contabila.codit import PostgresCoditStore
    from poarta_contabila.extract.contract import PostgresExtractStore
    from poarta_contabila.extract.document_ai import document_ai_from_env
    from poarta_contabila.filings import PostgresFilingStore
    from poarta_contabila.jev import PostgresJevCache, jev_from_env
    from poarta_contabila.jobs import PostgresJobStore
    from poarta_contabila.model_roles import PostgresModelCallStore
    from poarta_contabila.packages import PostgresPackageStore
    from poarta_contabila.period_diff import PostgresPeriodStore
    from poarta_contabila.reading_waits import (
        PostgresReadingChoiceStore,
        PostgresReadingWaitStore,
    )
    from poarta_contabila.recon.pre import PostgresReconStore
    from poarta_contabila.registry import PostgresRegistry
    from poarta_contabila.rules import PostgresRuleStore

    pool = ConnectionPool(
        dsn,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    model_mode = os.environ.get("MODEL_CALLS", "off").strip().lower() or "off"
    runtime = build_runtime(
        catalog=catalog,
        jobs=PostgresJobStore(dsn),
        packages=PostgresPackageStore(dsn),
        blobs=S3BlobStore(s3),
        registry=PostgresRegistry(dsn),
        recon=PostgresReconStore(dsn),
        agent_store=PostgresAgentStore(dsn),
        checkpointer=checkpointer,
        periods=PostgresPeriodStore(dsn),
        rules=PostgresRuleStore(dsn),
        closes=PostgresCloseStore(dsn),
        codits=PostgresCoditStore(dsn),
        filings=PostgresFilingStore(dsn),
        jev=None if model_mode in ("dry", "live") else jev_from_env(PostgresJevCache(dsn)),
        jev_cache=PostgresJevCache(dsn),
        model_calls=PostgresModelCallStore(dsn),
        model_mode=model_mode,
        statement_reader=document_ai_from_env(),
        extracts=PostgresExtractStore(dsn),
        reading_waits=PostgresReadingWaitStore(dsn),
        reading_choices=PostgresReadingChoiceStore(dsn),
        answers=PostgresAnswerLog(dsn),
        provider_policies=PostgresPolicyStore(dsn),
        role_choices=PostgresRoleChoiceStore(dsn),
        batches=PostgresBatchIndex(dsn),
    )
    # WP-36: Gemini reads synthetic tenants' statements directly (MODEL_CALLS=live + key)
    runtime.gemini_reader = gemini_reader_from_env(
        catalog.model_roles, runtime.model_calls, runtime._synthetic, runtime.model_mode
    )
    return runtime, "ok"
