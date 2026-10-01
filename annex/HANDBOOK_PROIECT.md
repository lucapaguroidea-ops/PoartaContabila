# Handbook proiect — motor operațional RO → SAGA C

Draft. SoT pentru cataloage: `HANDBOOK_CATALOAGE.md` + YAML-urile `ARTICOLE_*`.  
Acest fișier e **harta sistemului**, nu legea rândurilor.

---

## 1. Ce este

Pipeline de cabinet: dump haotic de documente → sortare fiscală → Job-uri → itinerarii catalogate → XML/DBF SAGA C → reconciliere cu Registrul Jurnal / Cartea Mare → închidere lună + CO.DiT.

**Nu** e un al doilea registru. SAGA e sink-ul legal. Motorul e control + flux + cataloage.

Stivă v1:

```
LangGraph (Python)     4 grafuri compilate
Postgres checkpointer  thread-uri batch/job/recon/close
Mongo (sau PG)         Job, Pack, CO.DiT, CloseRun
Railway / VPS          app + bucket
Document AI (EU)       extract v1 → Docling ulterior
SAGA C pe VPS          FDB read-only opțional; scriere XML + agent UI
Jev                    clasificator pe anexe, nu lege
```

---

## 2. Patru grafuri

| `graph_id` | Thread | Intrare | Ieșire |
|---|---|---|---|
| `folder_triage` | `batch:{id}` | folder dump | pack-uri + emit |
| `ingest_source_doc` | `job:{id}` | Job | packaged / acked / already_in_sink |
| `reconcile_sink` | `recon:{cui}:{period}` | Job-uri + RJ | verdict pre/post |
| `monthly_close` | `close:{cui}:{period}` | fereastră lock | file / hold + V4 |

Glue = Mongo ids. Nu `add_node(alt_graf_compilat)` în ingest.

---

## 3. Drumul unui document

```
_inbox
  sniff Jev → SourceDoc → aisle (SPV > foreign > bon CUI > extras > rest)
  pair UBL+PDF, fork bon cu/fără CUI
  emit dacă class + identity + primary + posting_eligible
    → Job (kind din ArticoleJobs)
ingest extract (UBL | MT940 | Document AI)
  bind Flux.matches
  dacă bon: Test A (pins 100 EUR) → nature Jev → ArticolBon.matches
  HITL first_n / always
  reconcile PRE  (deja în RJ? → stop XML)
  WriteModule XML/DBF + backup
  agent Validare → saga_doc_key → acked
  reconcile POST (cum s-a înregistrat)
close
  lock fereastră + CM + PeriodDiff
  V2 file|hold
  V4 patch CO.DiT (auto/saf_t; seed next pentru impozit)
```

---

## 4. Porți de emit (nu Jev)

```
class_gate      SourceDoc.posting_eligible
identity_gate   tenant / extras name|CUI / bon CUI e doar fork
primary_gate    UBL pentru RO; foreign fără SPV obligatoriu
emit            AND; fail closed
```

Bon cu CUI ≠ TVA deductibil. Asta e ArticolBon după emit.

---

## 5. CO.DiT

Document `{cui, period}`: axe (forma, impozit, tva, exig, auto, …) + pins copiate + `derive()` (id, hash, due[], watched).

Write: defaults exig → **T\*** → **F\*** → F7/A\* → derive.  
`auto` nu e în hash. Joburile `acked` nu se re-bindează la V4.

---

## 6. SAGA

- Citire: export RJ/CM → `80_sink` → `SinkLine[]` (FDB e ochi, nu poarta grafului).  
- Scriere: XML/DBF, user agent limitat, backup înainte, Validare umană/agent.  
- Fără `fdb_insert`. Rollback = Devalidare / storno / restore.  
- Idempotență: `export_key` + `seq` + `saga_doc_key`. Retry = „e deja acolo?”.

---

## 7. Reconciliere

Graf propriu. Fereastră `{cui, period}` până la close.

```
PRE   date+nr (factură) | date+gross (bon)
      grup nr_nota
      already_posted | absent | ambiguous
POST  how vs ArticolBon / 4428
det apoi llm_review independent (confirm|contest|abstain)
```

LLM nu e matcher. `contest` → HITL, nu flip.

---

## 8. Jev

Anexă (liste închise) + V0–V8.  
`matches()` întâi; `|cands|=1` → skip Jev.  
Off-list → HITL, nu rând YAML.

---

## 9. HITL

Kind ∈ `ArticoleHITL` ∩ `graph.allowed_hitl`.  
Resume Pydantic `extra=forbid`.  
Pattern-uri: XOR, approve/edit, completează CUI, leagă articol, așteaptă SAGA/RJ, contestă det, poartă lună, compensare.

---

## 10. Extract

v1 `document_ai` (Layout Parser pin EU).  
Adaptor: `normalized/markdown.md` + `tables.json` + `extract_meta`.  
Apoi `docling` pe același contract. UBL/MT940 rămân parsere dedicate.

---

## 11. Idempotență (pe scurt)

```
Job            (tenant_cui, source_hash)
thread         prefix + id
extract        file_hash + backend + version
XML            job:module:ver:seq
recon          job + stage + export_id
resume         thread + checkpoint + kind
close          (cui, period)
```

---

## 12. Invariante

1. SAGA e sink-ul; motorul nu e ledger.  
2. Catalogul e lege; Jev e vocabulare.  
3. Fail closed.  
4. Un thread_id prefixat corect.  
5. Extra keys pe Job/Pack/resume = forbid.  
6. Money/date = string.  
7. Compensare, nu rollback API.  
8. PDF RO fără UBL ≠ primary.  
9. Fără CUI pe bon ≠ deductibilitate.  
10. Material V2 ⇒ nu `file`.

---

## 13. Ordine de construcție

```
1. Schema Pack/Job/CO.DiT + T* F* + Pins
2. folder_triage + SourceDoc + anexă sniff + V*
3. emit + Jobs unique
4. ingest extract adaptor + Flux bind
5. ArticolBon + Test A
6. WriteModule fixture COPY + agent Validare
7. reconcile_sink + export RJ
8. monthly_close V2
9. V4
10. Docling swap
```

Nu începeți cu OpenClaw / multi-tool chat.

---

## 14. Repo artifacts (acum)

```
HANDBOOK_PROIECT.md
HANDBOOK_CATALOAGE.md
ARTICOLE_*.yaml / ARTICOL_BON_v1.yaml
ARTICOLE_CODIT_T_v1.yaml
ARTICOLE_CODIT_PAIRS_v1.yaml
ARTICOLE_HITL_v1.yaml
JEV_ANNEX*.yaml  JEV_VALIDATE_V_v1.yaml
test_jev_validate.py
LANGCLAW_CATALOG_v1.yaml          # arhivă
```

---

## 15. Vocabular

| Termen | Sens |
|---|---|
| Articol | rând de catalog (flux, bon, source, …) |
| ArticolFlux | itinerariu în *un* graf |
| Pack | dosar normalizat al unui document-sursă |
| Job | unitate de posting după emit |
| CloseRun | unitate de lună |
| SinkLine | linie RJ/CM normalizată |
| CO.DiT | profil fiscal {cui,period} |
| Annex | liste Jev |
| V* | porți pe JevOut |
| T* F* | perechi CO.DiT |

---

*Proiect handbook v1 — 2026-03-30. Actualizați §14 când adăugați SoT nou.*
)
