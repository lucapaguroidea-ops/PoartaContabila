# Owner checklist — what only the owner can check or set

Each item says where the answer goes. Nothing here needs a code change to be recorded; send
the answer and the session records it.

## Models and OpenRouter (00_LAW §3.5, `catalog/50_control/ARTICOLE_MODEL_ROLES_v1.yaml`)

- [x] **Exact OpenRouter model ids** (2026-10-03): Jev `typesafe/jev-1.13` (all System One
      roles), GLM `z-ai/glm-5.3` for every System Two role (WP-51: DeepSeek trains on prompts).
- [x] **Is Jev (TypeSafe AI) listed on OpenRouter?** Yes (2026-10-03): `typesafe/jev-1.13`
      through the Decisions endpoint; a `noul` comes back as a probability, a `choice` with
      its confidence and per-option probabilities (RESEARCH_LOG R2). Where TypeSafe processes
      data is not documented: synthetic tenants only.
- [ ] **Spend per key** (WP-56): `GET /model-keys` reads each key's spend and what is left
      from OpenRouter (`/api/v1/key`, with the key itself) — nothing to set up. For the whole
      account (credits bought and used, every key by name), optionally add a management key on
      Railway as `OPENROUTER_MANAGEMENT_KEY` (OpenRouter → Settings → Management keys). The
      service only reads with it; a management key can create and delete keys, so keep it on
      Railway only.
- [x] **Approved alternates** (2026-10-03, 00_LAW §8 A7): System Two `z-ai/glm-5.3` on
      `together`, then `moonshotai/kimi-k2.6`; switched to by themselves while Z.AI fails the
      data policy. If no pin passes: `POST /model-roles/{role_id}/choice`.
- [x] **Provider pins** (2026-10-03): each model's own provider only — `typesafe`,
      `z-ai`; fallbacks off, data collection denied.
- [x] **OpenRouter keys** on Railway (2026-10-03): `OPENROUTER_SYS1_API_KEY` for Jev and
      `OPENROUTER_SYS2_API_KEY` for System Two, each with its own credit limit (owner, WP-55).
- [x] **Gemini direct for synthetic data** (decided 2026-10-02, WP-36): the AI Studio key is
      on Railway as `GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC`. It replaces the OpenRouter BYOK route
      for document reading, so the BYOK key in OpenRouter can be removed.
- [x] **Gemini model id for AI Studio**: `gemini-3.8-flash`, pinned on both document-reading
      roles (2026-10-02).
- [x] **Model tiers and free-tier limits** (00_LAW §8 A4, 2026-10-02): everyday
      `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite` (15 RPM); strong `gemini-3.8-flash`,
      `gemini-3.7-flash` (5 RPM, 20 RPD). Update `rate_limits` if AI Studio's page changes.
- [x] **Lite models confirmed** (AI Studio rate-limit table, 2026-10-02): 3.5 and 3.1 Flash
      Lite, 15 RPM, 250K TPM, 500 RPD each; `gemini-3.5-flash-lite` read 6/6 live.
- [x] **Reserve models** (00_LAW §8 A6, 2026-10-02): `gemini-3.6-flash`, `gemini-3.5-flash`,
      read with only on a day you choose `reserve` (`POST /reading/{cui}/choice`).
- [ ] **Exact ids of Gemini 3 Flash and Gemini 2.5 Flash**: `gemini-3-flash` and
      `gemini-2.5-flash` answer 404; AI Studio's "Get code" shows the id to use.
- [ ] **Optional:** `READING_RETRY_SECONDS` on Railway (default 60) — how often parked
      statements are read again; 0 turns the background round off.
- [ ] **Turn it on**: set `MODEL_CALLS=live` on Railway (from `dry`). Only synthetic document
      reading sends; every other role keeps recording. Check `GET /model-roles` shows
      `ocr_extract` with `key_set: true`.
- [ ] **Test it**: `GRAPHUSERTOKEN_OPERATOR=… uv run python -m poarta_contabila.smoke --base-url
      https://<domain> --ocr`. The step "statement PDF read" should mint a job, and
      `GET /model-calls?role=ocr_extract` should show `sent`.
- [ ] **Reading evaluation** (after the `--ocr` smoke works):
      `GRAPHUSERTOKEN_OPERATOR=… uv run python -m poarta_contabila.ocr_eval --base-url https://<domain>`.
      Six known statements, scored. To compare a Pro model on the hard cases, add
      `--model <bare id> --case two_pages --case dense`. `--write-pdfs ./eval-pdfs` saves the
      PDFs to look at.
- [ ] **Gemini API terms for the free tier** (Google's "Unpaid Services"): free tier for synthetic
      tests only; client documents only on the EU host (decided 2026-10-02).
- [ ] **Railway variables** (project `faithful-mercy`):
      `OPENROUTER_BASE_URL`, `OPENROUTER_SYS1_API_KEY`, `OPENROUTER_SYS2_API_KEY`,
      `MODEL_CALLS=dry` to start (`live` for the Gemini step above). One OpenRouter key per system
      (WP-55), each with its own credit limit. `GET /model-roles` shows which keys are set (never
      values).
- [ ] **Railway domain**: the `PoartaContabila` service has no public domain (checked
      2026-10-02), so the operator API cannot be reached from outside. Generate one (service →
      Settings → Networking) before testing on Railway; it runs PR #5's code until PR #6 merges.
- [ ] **Let the build agent run the smoke and the evaluation** (WP-38):
      1. Generate the service's public domain (service → Settings → Networking).
      2. In this Claude Code cloud environment's settings (environment menu in the session's
         title bar → Edit), add the variable `GRAPHUSERTOKEN_CLAUDE_SYSBUILDER` with the same
         value as on Railway. Never paste it into the chat; a new session picks it up.
      3. Make sure that environment's network access allows `*.up.railway.app`.
      Its token opens synthetic tenants only; a client tenant answers 403.
- [ ] **Tokens before the domain goes public**: `GET /ready` must show `operator_token: ok`
      and `agent_token: ok` (at least 32 characters each, and different). If not, rotate them in
      Railway's variables; it never shows the values.
- [ ] **Smoke run on Railway**, once the domain exists and `MODEL_CALLS=dry` is set:
      `GRAPHUSERTOKEN_OPERATOR=… uv run python -m poarta_contabila.smoke --base-url https://<domain>`.
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
