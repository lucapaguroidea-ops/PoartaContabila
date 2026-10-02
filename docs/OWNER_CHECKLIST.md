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
- [ ] **Gemini through OpenRouter BYOK**: does OpenRouter's BYOK list Google AI Studio, and does
      the AI Studio free tier still apply through it (quota, fees)?
- [ ] **Gemini API terms for the free tier** (Google's "Unpaid Services"): free tier for synthetic
      tests only; client documents only on the EU host (decided 2026-10-02).
- [ ] **Railway variables** (project `faithful-mercy`):
      `OPENROUTER_BASE_URL`, `OPENROUTER_JEV_API_KEY`, `OPENROUTER_SYS2_API_KEY`,
      `OPENROUTER_OCR_API_KEY`, `MODEL_CALLS=dry` to start. One OpenRouter key per role group,
      each with its own credit limit. `GET /model-roles` shows which keys are set (never values).
- [ ] **Test tenants** carry `"data_class": "synthetic"` (`PUT /tenants/{cui}`); any other tenant
      is client data and no model is called for it until the EU route exists.
- [ ] **Scaleway (EU)**: which Scaleway-hosted models serve which role, once we leave synthetic
      data. It becomes each role's `eu_route`.
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
