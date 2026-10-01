# Handbook cataloage LangClaw / LangGraph

Status: draft Lane B. Nimic `active` până la fixture + approve accountant.  
Instanțele (Pack, Job, CO.DiT, CloseRun, Batch) **nu** sunt cataloage.

---

## 1. Hartă

```
Lege / firmă
  ArticolePins
  ArticoleCoDitT          T*
  ArticoleCoDitPairs      F* + F7 + A* + R1
  CO.DiT                  document {cui,period}  ← nu catalog

Document → SAGA
  ArticoleSourceDoc
  ArticoleJobs
  ArticoleGraph
  ArticoleFlux
  ArticolBon
  ArticoleWriteModule

Adevăr sink
  ArticoleReconcile
  ArticoleClose

Control
  ArticoleHITL
  JevAnnex + JevValidateV
```

---

## 2. Inventar fișiere

| Catalog | Fișier | Întrebare |
|---|---|---|
| ArticolePins | `ARTICOLE_PINS_v1.yaml` | cote / 100 EUR / plafoane anuale |
| ArticoleCoDitT | `ARTICOLE_CODIT_T_v1.yaml` | TVA × exig legal? |
| ArticoleCoDitPairs | `ARTICOLE_CODIT_PAIRS_v1.yaml` | formă × impozit? hibrizi F7? |
| ArticoleSourceDoc | `ARTICOLE_SOURCE_DOC_v1.yaml` | ce e fișierul? emit? extract? |
| ArticoleJobs | `ARTICOLE_JOBS_v1.yaml` | ce fel de Job? |
| ArticoleGraph | `ARTICOLE_GRAPH_v1.yaml` | care mașină compilată? |
| ArticoleFlux | `ARTICOLE_FLUX_v1.yaml` | care itinerariu? |
| ArticolBon | `ARTICOL_BON_v1.yaml` | Test B bon? |
| ArticoleWriteModule | `ARTICOLE_WRITE_MODULE_v1.yaml` | ce gură SAGA? |
| ArticoleReconcile | `ARTICOLE_RECONCILE_v1.yaml` | e în RJ? cum? |
| ArticoleClose | `ARTICOLE_CLOSE_v1.yaml` | file / V4? |
| ArticoleHITL | `ARTICOLE_HITL_v1.yaml` | ce JSON de resume? |
| JevAnnex | `JEV_ANNEX_v1.yaml` | ce poate spune Jev la nod? |
| JevAnnex exemplu | `JEV_ANNEX_EXAMPLE_source_bon.yaml` | choices sintetizate |
| JevValidateV | `JEV_VALIDATE_V_v1.yaml` | porți V0–V8 |
| (schiță veche) | `LANGCLAW_CATALOG_v1.yaml` | nu mai e SoT |

Lane A (nu Articole globale): `maps`, `name_to_cui`, `iban_to_cui`, `explained_rules`.

---

## 3. Comparație scurtă

| | Grain | Matching | Scrie SAGA |
|---|---|---|---|
| Pins | an | copy on seed | nu |
| T* F* | write CO.DiT | if/and pe axe | nu |
| SourceDoc | fișier | sniff + anexă Jev | nu |
| Jobs | emit | tabel source→kind | nu |
| Graph | app | alegere explicită | nu |
| Flux | bind | require/forbid/filters | numește module |
| Bon | după flux bon | nature + A_band + axe | numește modul |
| WriteModule | package | id din flux | **da** |
| Reconcile | fereastră | chei RJ + matches flux recon | nu |
| Close | lună | kind + V2 | nu |
| HITL | interrupt | kind + resume schema | nu (ack SAGA = agent) |
| Jev V* | tool out | V0–V8 | nu |

---

## 4. Ordine de citire la runtime

```
dump
  SourceDoc + Jev sniff (V*)     → aisle, extract
  HITL define_class / pair / cui
emit
  Jobs + CO.DiT (Pins, T*, F*)   → Job sau skip
ingest
  Graph ingest
  Flux.matches → articol_id
  Bon.matches dacă job_bon
  HITL v3 / articol_bon
  invoke reconcile_sink PRE
  WriteModule package
  HITL wait_validare
reconcile_sink
  Reconcile flux + profile
  Jev review (alt hash)
  HITL ambiguous / how
close
  Close kind
  Reconcile POST + CM
  HITL v2 / v4
  T* F* din nou pe write CO.DiT
```

---

## 5. Reguli de întreținere

1. Id nou în părinte → regenerați `JevAnnex.choices` + bump hash.  
2. `status: draft` până la fixture COPY firmă (WriteModule) / accountant (Bon, Flux).  
3. Job îngheață `articol_id` + `schema_version` + `client_type_hash` + `jev_annex_hash`.  
4. Nu copiați T*/F* în `Flux.forbid`.  
5. Nu inventați `ArticoleJev` / `ArticolePack` / `ArticoleEmit`.  
6. HITL kind necunoscut = fail closed.  
7. `LANGCLAW_CATALOG_v1.yaml` e arhivă; diff-urile noi merg în fișierul Articole*.

---

## 6. Lane B vs Lane A

| Lane B (YAML global) | Lane A (per client) |
|---|---|
| toate Articole* + T* F* + HITL + Jev V/anexă | maps 401.xxxxx |
| pins anuale RO | name_to_cui, iban_to_cui |
| nature_code enum | explained_rules pe RJ |

---

## 7. Teste minime pe catalog

| Catalog | Test |
|---|---|
| T* | neplatitor + încasare → T1 |
| F* | pfa + micro → F3 |
| SourceDoc | PDF RO → nu emit |
| Jobs | același source_hash → un job_id |
| Flux | inbound + storno false → ro_efactura_inbound |
| Bon | fara_cui → blocked_no_cui |
| Reconcile | F123+dată unic → already_posted |
| HITL | extra field pe resume → ValidationError |
| Jev V* | `test_jev_validate.py` (10) |

---

## 8. Ce catalog deschideți când…

| Problemă | Catalog |
|---|---|
| aisle greșit | SourceDoc + anexă sniff |
| dublu XML | Jobs unique + Reconcile PRE |
| 4426 pe bon fără CUI | Bon + Reconcile POST how |
| D100 pe PFA | F3 |
| 4428 pe neplatitor | T1 |
| Jev a zis etichetă nouă | V3 + HITL, nu YAML din Jev |
| close material | Close + Reconcile + explained_rules |
| SAGA gură nouă | WriteModule + fixture, apoi Flux.used_by |

---

*Handbook v1 — oglindă a fișierelor din `artifacts/` la 2026-03-30.*
)
