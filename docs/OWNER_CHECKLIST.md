# Owner checklist — what only the owner can check or set

Each item says where the answer goes. Nothing here needs a code change to be recorded; send
the answer and the session records it.

## Models and OpenRouter (00_LAW §3.5, `catalog/50_control/ARTICOLE_MODEL_ROLES_v1.yaml`)

- [ ] **Exact OpenRouter model ids**, one per family: DeepSeek, GLM, Gemini, and Jev if listed.
      No alias (`…latest`), no `openrouter/auto`, no `:free` variant. They go into each role's
      `model:`; until then every role refuses and a person is asked.
- [ ] **Is Jev (TypeSafe AI) listed on OpenRouter?** If yes: its model id, and one example
      response (key removed) showing whether the `noul` probability / `choice` confidence come
      through. If no: Jev's roles take the direct route of `RESEARCH_LOG.md` R2
      (`JEV_BASE_URL`, `JEV_API_KEY`).
- [ ] **Provider pins**: for each role, the provider(s) OpenRouter may use (`provider.only`);
      fallbacks stay off and data collection denied.
- [x] **Gemini direct for synthetic data** (decided 2026-10-02, WP-36): the AI Studio key is
      on Railway as `GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC`. It replaces the OpenRouter BYOK route
      for document reading, so the BYOK key in OpenRouter can be removed.
- [x] **Gemini model id for AI Studio**: `gemini-3.8-flash`, pinned on both document-reading
      roles (2026-10-02).
- [ ] **Turn it on**: set `MODEL_CALLS=live` on Railway (from `dry`). Only synthetic document
      reading sends; every other role keeps recording. Check `GET /model-roles` shows
      `ocr_extract` with `key_set: true`.
- [ ] **Test it**: `OPERATOR_TOKEN=… uv run python -m poarta_contabila.smoke --base-url
      https://<domain> --ocr`. The step "statement PDF read" should mint a job, and
      `GET /model-calls?role=ocr_extract` should show `sent`.
- [ ] **Reading evaluation** (after the `--ocr` smoke works):
      `OPERATOR_TOKEN=… uv run python -m poarta_contabila.ocr_eval --base-url https://<domain>`.
      Six known statements, scored. To compare a Pro model on the hard cases, add
      `--model <bare id> --case two_pages --case dense`. `--write-pdfs ./eval-pdfs` saves the
      PDFs to look at.
- [ ] **Gemini API terms for the free tier** (Google's "Unpaid Services"): free tier for synthetic
      tests only; client documents only on the EU host (decided 2026-10-02).
- [ ] **Railway variables** (project `faithful-mercy`):
      `OPENROUTER_BASE_URL`, `OPENROUTER_JEV_API_KEY`, `OPENROUTER_SYS2_API_KEY`,
      `MODEL_CALLS=dry` to start (`live` for the Gemini step above). One OpenRouter key per role group,
      each with its own credit limit. `GET /model-roles` shows which keys are set (never values).
- [ ] **Railway domain**: the `PoartaContabila` service has no public domain (checked
      2026-10-02), so the operator API cannot be reached from outside. Generate one (service →
      Settings → Networking) before testing on Railway; it runs PR #5's code until PR #6 merges.
- [ ] **Tokens before the domain goes public**: `GET /ready` must show `operator_token: ok`
      and `agent_token: ok` (at least 32 characters each, and different). If not, rotate them in
      Railway's variables; it never shows the values.
- [ ] **Smoke run on Railway**, once the domain exists and `MODEL_CALLS=dry` is set:
      `OPERATOR_TOKEN=… uv run python -m poarta_contabila.smoke --base-url https://<domain>`.
      It writes only the invented firm `1000009`, and prints each step and what every model
      role would have been sent, by graph and node. `--local` shows the same without a server.
- [ ] **Test tenants** carry `"data_class": "synthetic"` (`PUT /tenants/{cui}`); any other tenant
      is client data and no model is called for it until the EU route exists.
- [ ] **Decision: the EU route per model family** (`00_LAW.md` §3 invariant 5 names Scaleway
      only). Proposed:
      - document reading (Gemini): Vertex AI in an EU region (`docs/EU_VERTEX_SETUP.md`);
      - System Two (DeepSeek / GLM): Scaleway;
      - Jev: open, because where it processes data is unknown.
      The law changes once you decide.
- [ ] **Scaleway (EU)**: which Scaleway-hosted models serve which System Two role, once we leave
      synthetic data. It becomes each role's `eu_route`.
- [ ] **Vertex AI EU setup** (`docs/EU_VERTEX_SETUP.md`, reviewed 2026-10-02). **Blocked by:**
      - the EU-route decision above;
      - a domain you control (Cloud Identity);
      - the live sender;
      - leaving synthetic data.
      Do §A–§D then, and tick §H before the first client document.
- [ ] **Role cards** (WP-25): read each role's `card` in `ARTICOLE_MODEL_ROLES_v1.yaml` — Jev's
      questions and criteria, Gemini's extraction rules, the System Two brief
      (`GET /model-roles` shows it rendered). Change wording in the catalog; the hash changes and
      old cached answers are not reused.
- [ ] **The live sender**: this build session was not permitted to write the outbound call with
      a key. Either allow it (Claude Code permission rule) or have it written elsewhere; it plugs
      into `role_transport` in `poarta_contabila/jev.py`.

## SAGA copy firm (`docs/COPY_FIRM_TEST.md`)

- [ ] §1–§2: the four fixture imports and the two guard tests.
- [ ] §3: SAGA's own sample XML (`FMT-1` and its storno `FMT-1s`).
- [ ] §4: what to send back.
- [ ] §5 (optional): the TVA la încasare firm, for the 4428 bookings.

## Network access of build sessions

- [ ] `docs.typesafe.ai`, `api.typesafe.ai`, `openrouter.ai`, `manual.sagasoft.ro` are refused
      by the cloud environment's network policy. Allow them (environment settings → Network
      access) if a session should read or call them.

## Decisions still open

- [ ] WP-D3: non-payer reverse charge books, 4423 vs 446x.
