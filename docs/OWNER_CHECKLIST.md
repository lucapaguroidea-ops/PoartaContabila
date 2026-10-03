# Owner checklist — what only the owner can check or set

Each item says where the answer goes. Send the answer and a session records it. State as of
2026-10-03.

## Open — yours to do

- [ ] **Raise the System Two key's limit** (`OPENROUTER_SYS2_API_KEY`): $1.22 left of $2 a month
      on 2026-10-03, after the model comparisons. Normal use is about $0.003 an explanation;
      the live sample (WP-74) stops when a key has less than $0.50 left.
- [ ] **Optional: account-wide spend** (WP-56): add a management key on Railway as
      `OPENROUTER_MANAGEMENT_KEY` (OpenRouter → Settings → Management keys). The service only
      reads with it; it can create and delete keys, so keep it on Railway only.
- [ ] **Review page for accountants** (WP-66, WP-67): `https://<domain>/review`. Each person
      signs in with the operator token and their own name. Per-person logins are a later WP.
- [ ] **Role cards** (WP-25): read each role's `card` in `ARTICOLE_MODEL_ROLES_v1.yaml` (Jev's
      questions, the reading rules, the System Two brief; `GET /model-roles` shows them
      rendered). Change wording in the catalog; the hash changes, old cached answers are not
      reused.
- [ ] **Exact ids of Gemini 3 Flash and Gemini 2.5 Flash**: `gemini-3-flash` and
      `gemini-2.5-flash` answered 404; AI Studio's "Get code" shows the id to use.
- [ ] **SAGA copy firm** (`docs/COPY_FIRM_TEST.md`, WP-03):
      - §1–§2: the four fixture imports and the two guard tests;
      - §3: SAGA's own sample XML (`FMT-1` and its storno `FMT-1s`);
      - §4: what to send back;
      - §5 (optional): the TVA la încasare firm, for the 4428 bookings.
- [ ] **Housekeeping, when convenient** (nothing depends on it):
      - Railway variable `OPENROUTER_BASE_URL` is read by no code (ARCHITECTURE §14): remove it.
      - The previous deployment's Railway project (`comfortable-nature`, 00_LAW §8 A1 §6) is not
        used by this service: delete it once you no longer need it.
      - GitHub: every `claude/*` branch is merged into `main` (2026-10-03). Delete the old ones,
        but not the branch of a session still running.
      - Check that `poarta-bucket` was created in Railway's EU region (`docs/EU_VERTEX_SETUP.md`
        §G); a bucket's region cannot change later.

## Decisions still open

From the synthetic-data program (WP-69 – WP-74; `docs/CATALOG_GAPS.md`), 2026-10-03:

- [ ] **Storno SAGA mouths (G5).** An approved credit note stops at `needs_human`: no
      `storno_intrare_xml` / `storno_iesire_xml` is rendered, because no tag is invented
      (AGENTS). Send SAGA's own storno sample (`docs/COPY_FIRM_TEST.md` §3, `FMT-1s`) and say how
      SAGA imports a storno (negative amounts on the same mouth, or another file).
- [ ] **A foreign partner on the invoice mouths (G1).** A sale to an EU business (or a purchase
      from abroad, once FX exists) needs `ClientCIF` / `FurnizorCIF`: does SAGA's import take a
      foreign VAT id (`NL…`) there? One copy-firm import of such an invoice answers it.
- [ ] **NextUp job settlement (G9).** A NextUp firm's document uploaded before it is posted in
      NextUp stops at `needs_human` (no PreFile, A2 §3) and nothing settles it, so the month
      stays material. Proposal: it waits until NextUp's journal shows it, then
      `already_in_sink`. Yes / no / other.
- [ ] **A report part waiting for its XML (G3).** `C2_waiting_for_xml` cannot be computed: a
      `decont_split` part carries only its hash. Should the answer also carry the part's number
      and date? That changes an existing HITL kind's answer shape: say whether it needs a dated
      00_LAW amendment (§7) or may enter as draft.
- [ ] **C0's implied VAT accounts (G6), for an accountant.** Entered as `[de confirmat]`:
      TVA la încasare 4428 at the invoice, moved 4428 → 4426 / 4427 by the paid share (half up);
      neplătitor VAT in the cost; reverse charge for a payer 4426 = 4427 at the standard rate.
      Confirm or correct each.
- [ ] **Journal types in the synthetic books.** The generator writes `Diverse` (notes), `Casa`
      (cash) and `Salarii` (payroll) as SAGA's journal types; only `Intrari`, `Iesiri`, `Banca`
      are read as documents. Confirm SAGA's names on the copy firm.
- [ ] **WP-74 go-ahead**: ≤ 10 documents, one approval, one close of the new synthetic firms on
      production with `MODEL_CALLS=live`, stopping when a key has less than $0.50 left (see the
      first item above for the System Two key's balance).

- [ ] **WP-D3**: non-payer reverse charge books, 4423 vs 446x. Until then
      `foreign_rc_neplatitor` always goes to a person.
- [ ] **WP-D4**: the EU route per model family (Gemini on Vertex AI `eu`; GLM on Scaleway or
      OpenRouter EU; Jev: none, a person, or an amendment). Kept open until the work reaches
      client data (owner, 2026-10-03). Then: `docs/EU_VERTEX_SETUP.md` §A–§D, and §H before the
      first client document.

## Done

- [x] **Models** (2026-10-03): Jev `typesafe/jev-1.13` on TypeSafe for all System One roles;
      `z-ai/glm-5.3` on Z.AI for every System Two role (WP-51: DeepSeek trains on prompts);
      each pin's provider only, fallbacks off, data collection denied.
- [x] **Approved alternates** (00_LAW §8 A7): GLM 5.3 on Together, then Kimi K2.6; used by
      themselves only while Z.AI fails the data policy. If no pin passes:
      `POST /model-roles/{role_id}/choice`. Compared 2026-10-03 (WP-59 – WP-61): GLM on Z.AI
      stays first.
- [x] **System Two in English** with the Romanian domain words kept, questions dated `as_of`
      (WP-63).
- [x] **OpenRouter keys** on Railway: `OPENROUTER_SYS1_API_KEY` (Jev), `OPENROUTER_SYS2_API_KEY`
      (System Two), each with its own limit (WP-55). Credits bought 2026-10-03: no key is on
      the free tier any more (RESEARCH_LOG R4).
- [x] **Gemini direct for synthetic data** (WP-36): `GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC` on
      Railway; the OpenRouter BYOK key for Gemini can be removed.
- [x] **Reading tiers** (00_LAW §8 A4 – A6): everyday `gemini-3.5-flash-lite`,
      `gemini-3.1-flash-lite`; strong `gemini-3.8-flash`, `gemini-3.7-flash`; reserve
      `gemini-3.5-flash`, `gemini-3-flash-preview`, `gemini-3.6-flash` on a day you choose
      `reserve`.
- [x] **Live**: `MODEL_CALLS=live` on Railway; Jev, System Two and reading send for synthetic
      tenants only.
- [x] **Domain and tokens**: `poartacontabila-production.up.railway.app`; `GET /ready` shows
      every token `ok` (2026-10-03). The build agent's token is set in the cloud environment,
      so sessions run the smoke run and the evaluations themselves.
- [x] **Smoke run on Railway** (WP-29): the invented firm `1000009`, both months, the approval
      and close explanations (WP-64).
- [x] **Test tenants** carry `"data_class": "synthetic"`; any other tenant is client data and no
      model is called for it until WP-D4.
- [x] **Network**: build sessions reach `openrouter.ai` and the Railway domain. If a session
      must read `docs.typesafe.ai` or `manual.sagasoft.ro` and is refused, allow them in the
      environment's network settings.
