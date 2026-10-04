# Research log

Rule (`LAW.md` L19): never guess an external format or API.
Each item names the question, the official URL, a short quote, the date it was read, and what
the code takes from it. A page that cannot be read gives nothing to build: the code keeps a
typed stub that refuses (fail closed) and the item says what the owner must do.

## R1 · SAGA C "Import date": invoices, receipts, payments, nomenclatures — WP-03

- Question: file names, root and child tags, value formats of SAGA C's XML import for invoices
  (`iesire_factura_xml` / `intrare_factura_xml`), receipts and payments (`incasare_xml` /
  `plata_xml`), partners and articles (`parteneri_xml` / `articole_xml`).
- Official URL: https://manual.sagasoft.ro/sagac/topic-76-import-date.html — 2026-10-01 **not
  read** (the build session's network policy denied the host).
- 2026-10-02: **read** instead from SAGA C's own help, printed to PDF by the owner from the
  installed program (7 chapters, each page stamped `02/10/2026`). The prints are not in this
  repo (SAGA's text). Section **Diverse → Import date**, pages 7–15 of 29, unless noted.
- Quotes (Romanian as printed):
  - Scope: "Ecranul este destinat importului din fișiere XML generate din programe Saga sau
    din alte aplicații, care respectă structura prezentată mai jos."
  - Sync: "dacă sincronizarea se face după "Nr.+data", se vor importa doar documentele cu
    număr şi dată care nu există deja în baza de date."
  - Not validated: "în cazul intrărilor şi ieşirilor datele importate nu sunt validate."
    Undo: "Pentru anularea importului de intrări şi ieşiri, validate grupat după import,
    trebuie ca acestea să fie devalidate în prealabil în ecranele de intrări sau ieşiri."
  - Backup: "Înainte de import, efectuați o salvare a bazei de date."
  - Routing: "Facturile în format XML se vor importa în ecranul "Intrari" când codul fiscal
    al firmei se regăsește la eticheta ClientCIF din XML și în ecranul"Ieșiri" când se
    găsește le eticheta FurnizorCIF."
  - Invoices: "Numele fişierului trebuie să fie în formatul următor: F_<cod-fiscal>_<numar-
    factura>_<data-factura>.xml." "Pentru a importa mai multe facturi concomitent, repetaţi
    secvenţa <Factura>." Tags, in the manual's order (`?` = printed "Opțional"):

    ```
    <Facturi><Factura>
      <Antet> FurnizorNume FurnizorCIF FurnizorNrRegCom FurnizorCapital FurnizorTara
        FurnizorLocalitate FurnizorJudet FurnizorAdresa FurnizorTelefon FurnizorMail
        FurnizorBanca FurnizorIBAN FurnizorInformatiiSuplimentare GUID_cod_client?
        ClientNume ClientInformatiiSuplimentare ClientCIF ClientNrRegCom ClientJudet
        ClientTara ClientLocalitate ClientAdresa ClientBanca ClientIBAN ClientTelefon
        ClientMail FacturaNumar FacturaData FacturaScadenta FacturaTaxareInversa (Da/Nu)
        FacturaTVAIncasare (Da/Nu) FacturaTip? FacturaInformatiiSuplimentare
        FacturaMoneda ("Opţional pentru RON") FacturaGreutate FacturaAccize?
        FacturaIndexSPV ("ID-ul de încărcare al e-Facturilor în SPV") Cod? </Antet>
      <Detalii><Continut><Linie> LinieNrCrt Gestiune? Activitate? Descriere
        CodArticolFurnizor? CodArticolClient? GUID_cod_articol? CodBare?
        InformatiiSuplimentare? UM Cantitate Pret Valoare ProcTVA? TVA Cont? TipDeducere?
        PretVanzare? </Linie>…</Continut></Detalii>
      <FacturaID> sau <GUID_factura>
    </Factura>…</Facturi>
    ```

    `FacturaID`: "(Opţional, ID unic, din aplicatia proprie, pentru identificarea încasării.
    Asocierea cu ID-ul unic din Saga se salvează în baza de date, pentru identificare
    ulterioară)".
  - Receipts: "Numele fişierului trebuie să fie în formatul următor: I_<data>.xml."
    "Pentru a importa mai multe încasări concomitent, repetaţi secvenţa <Linie>."
    `<Incasari><Linie>` `Data`, `Numar`, `Suma`, `Cont` ("Cont de trezorerie din clasa 5"),
    `ContClient` (Opţional), `Explicatie`, `FacturaID` ("Opţional - necesar pentru
    identificarea facturii încasate dacă aceasta a fost importată dintr-un XML"),
    `FacturaNumar` ("Opţional - permite identificarea facturii dupa număr"), `CodFiscal`
    (Opţional), `Moneda` (Opţional). "Fisierul XML de încasări se poate importa şi prin
    ecranele "Registru de casa" sau "Jurnal de banca". Această variantă permite asocierea
    încasărilor cu facturile corespunzătoare."
  - Payments: "P_<data>.xml", `<Plati><Linie>` with the same tags, `ContFurnizor` (Opţional)
    in place of `ContClient`; the same sentence about "Registru de casa" / "Jurnal de banca".
    The manual prints the row's closing tag as `<\Linie>`; read as `</Linie>`.
  - Nomenclatures: `FUR_<data>.xml` `<Furnizori><Linie>` and `CLI_<data>.xml`
    `<Clienti><Linie>` (`Cod`?, `Denumire`, `Cod_fiscal`, `Reg_com`, `Tara`, `Judet`,
    `Localitate`, `Adresa`?, `Cont_banca`?, `Banca`?, `Tel`?, `Email`?, clients `Discount`?,
    `Informatii`?, `Guid_cod`?); `ART_<data>.xml` `<Articole><Linie>` (`Cod`?, `Denumire`,
    `Cod_NC`, `Cod_CPV`, `UM`, `Tip`, `TVA`, `Pret`?, `Pret_TVA`?, `Cod_bare`?,
    `Informatii`?, `Guid_cod`?). "Nomenclatoarele se importă exclusiv în functie de codul
    intern."
  - Sample file: "Puteti obţine un model de XML cu date folosind tipărirea din ecranul
    "Ieșiri" și alegând opţiunea "Formular PDF" … În folderul TEMP\Facturi se va copia, pe
    lânga PDF, și XML-ul aferent facturii."
  - Elsewhere: the firm's fiscal code "se va înscrie fără a fi precedat de atributul fiscal …
    se va completa doar 1234 şi nu RO1234" (Configurare, p. 1); a partner checked as a VAT
    payer gets "atributul fiscal "RO"" added (Fisiere → Terti); supplier code 00001 → analytic
    "401.00001", client → "4111.00001" (Fisiere → Terti); Stornare gives "o înregistrare
    devalidată, cu valori negative a documentului selectat, şi cu litera "s" adăugată la
    numărul de document" (Operatii → Intrari); user type "Agent" is a sales agent with access
    "doar la clienții, furnizorii și facturile introduse de acesta", and non-Admin users cannot
    operate on "o perioadă închisă" nor devalidate "o lună închisă" (Configurare utilizatori);
    backup archives are named "ZZ-LL-AAAA_N.ZIP" in `salv_bd\cod_firma` (Administrare →
    Intretinere BD).
- Not in the manual, so `[de confirmat]` on a copy firm: value formats (dates in tags and in
  file names, decimal separator, a partner CIF with or without `RO`), whether an empty tag
  equals an absent one, whether `Cont` takes an analytic, what SAGA does with a receipt or
  payment that names no partner and no invoice, negative quantities in an imported invoice
  (storno), the length and characters allowed in `FacturaID`. The sample file above settles
  the formats for invoices.
- Code takes: the mouths write only tags listed above (`sinks/saga_xml.py`: invoices;
  receipts and payments without `ContClient` / `ContFurnizor` / `Moneda`).

## R2 · Jev (TypeSafe AI System One) API — `jev.py`

- Question: endpoint, authentication, request body (how a pack's questions are sent), response
  shape (how Choice / Score / Noul answers come back), timeouts, error codes, model pinning.
- Official URLs: https://docs.typesafe.ai/api.md, https://docs.typesafe.ai/primitives.md,
  https://docs.typesafe.ai/sdk/python/usage.md, https://docs.typesafe.ai/models.md
- 2026-10-01 and 2026-10-02: **not read.** `docs.typesafe.ai` and `api.typesafe.ai` were
  denied by the build session's network policy.
- 2026-10-02: **read instead** from TypeSafe AI's own Python SDK, `typesafe-sdk` 0.7.2 on PyPI
  (author "TypeSafe AI <support@typesafe.ai>", MIT; project URLs `docs.typesafe.ai/sdk/python/`
  and `github.com/typesafe-ai/typesafe-sdk-python`). Its wire models say "generated by
  datamodel-codegen: filename: https://api.typesafe.ai/openapi.json", so they are the vendor's
  API schema. The wheel was downloaded and read, not installed. Quotes (file in the wheel):
  - `constants.py`: `DEFAULT_BASE_URL = "https://api.typesafe.ai"`, `DEFAULT_MODEL =
    "jev-latest"`, `DEFAULT_TIMEOUT = 10.0`; env `TYPESAFE_API_KEY`, `TYPESAFE_BASE_URL`,
    `TYPESAFE_DEFAULT_MODEL`.
  - `_core/constants.py`: `SYSTEM_ONE_PATH = "/v1/systemone"`, `MODELS_PATH = "/v1/models"`,
    `REQUEST_ID_HEADER = "x-typesafe-request-id"`, `retry-after` / `retry-after-ms`.
  - `_core/transport.py` `prepare`: headers `Authorization: f"Bearer {config.api_key}"`,
    `Accept: application/json`, `Content-Type: application/json` with a body.
  - `_core/endpoints.py` `prepare_system_one`: body `{"state": state, "model": …,
    "questions": normalize_questions(questions)}`, `POST SYSTEM_ONE_PATH`.
  - `_schemas/models.py` `SystemOneRequest`: `state` "The content all questions in this request
    refer to." (string, object or array); `model` "Name or alias of the model to use. Available
    names are returned by GET /v1/models."; `questions` "each with a name you choose. The
    response uses those names to identify the answers." (min 1).
  - Questions: `NoulQuestion {type: "noul", instructions?, criteria?: {true?, false?}}`
    "a yes/no question or statement"; `ChoiceQuestion {type: "choice", instructions?, criteria:
    {name: description|null}}` "selects one of the choices in criteria"; `ScoreQuestion {type:
    "score", instructions?, criteria: [ordered levels]}` "Each description's position
    determines its score, starting at zero."
  - `SystemOneResponse {model, answers: {name: Answer}, usage: {input_tokens,
    output_tokens}}`; `model` "May differ from the alias supplied in the request".
    `NoulAnswer {type, noul}`: "Probability of a yes answer or a true statement, from 0 to 1 …
    values near 0.5 indicate uncertainty." `ChoiceAnswer {type, choice, confidence,
    probabilities}`: `confidence` "from 0 to 1 … use lower values to flag uncertain selections
    for review". `ScoreAnswer {type, score, confidence, legend, probabilities}`: `score`
    "Expected score: the probability-weighted average of the rubric levels."
  - `_core/errors.py`: 400 bad request, 401 authentication, 403 permission, 404, 422 server
    validation (`HTTPValidationError.detail[] {loc, msg, type}`), 429 rate limit (with
    `retry-after-ms` / `retry-after`), ≥ 500 internal; `_core/retry.py` default retried
    statuses `{408, 429, 500–599}`.
- Secondary, not a source for the code: a third-party tutorial ("How to Use TypeSafe AI Jev",
  aiagentskit.com, 2026-09-19, supplied by the owner as PDF). It shows the same SDK calls
  (`client.system_one(state=…, questions={…: Choice|Score|Noul(…)})`) but gives
  `TYPESAFE_BASE_URL="https://api.typesafe.ai/v1"`, which with the SDK's `/v1/systemone` path
  would double `/v1`; its benchmarks and prices are not the vendor's.
- What `jev.py` takes from this: `POST {JEV_BASE_URL}/v1/systemone`
  with the bearer key; each pack's fields asked as primitives — `v3_judge`: `accounts_ok` and
  `needs_human` as `noul`, `risk` as `choice` {low, medium, high}; `v2_declaration_gate`:
  `books_support_declaration` as `noul`, `gap_materiality` {none, immaterial, material} and
  `action` {file, hold, patch_maps, reopen} as `choice` — mapped to the closed models with
  fail-closed thresholds (`[de confirmat]`): yes only at `noul ≥ 0.90`; a `choice` stands only at
  `confidence ≥ 0.80`, else the cautious value (`risk: high` + `needs_human`; Layer 2
  `material` / `hold`); the model name in the cache key; `JEV_MODEL` (default `jev-latest`,
  pin a dated name from `GET /v1/models`). Any non-2xx, a body off this shape or a missing
  answer fails closed (a person is asked).
- Instruct: the owner (or a session permitted to write the outbound call) builds
  `jev.http_transport` from this item; `JEV_BASE_URL` / `JEV_API_KEY` (+ `JEV_MODEL`) are set on
  Railway by the owner.
- 2026-10-03: **through OpenRouter instead** (owner's choice of route), read from
  OpenRouter's own pages: `openrouter.ai/docs/guides/community/jev`,
  `…/community/jev-tutorial`, and the API reference "Submit a decisions (questions and
  answers) request" (`/docs/api/api-reference/alphadecisions/…`). Quotes:
  - Endpoint `POST https://openrouter.ai/api/alpha/decisions`, `Authorization: Bearer
    $OPENROUTER_API_KEY`; request `{"model": "typesafe/jev-1.13", "state": {…}, "questions":
    {name: {"type": "noul"|"choice"|"score", "instructions", "criteria"}}}`; optional
    `provider` (ProviderPreferences: `order`, `only`, `allow_fallbacks`, `data_collection`,
    `zdr`, …), `session_id`, `user`, `trace`.
  - Response: answers in a top-level `"answers"` object, "not in message choices":
    `{"type": "noul", "noul": 0.96}`; `{"type": "choice", "choice": "payments", "confidence":
    0.67, "probabilities": {…}}`; score with `score`, `confidence`, `probabilities`,
    `legend`; plus `id`, `model` (dated, e.g. `typesafe/jev-1.13-20260917`), `provider`,
    `usage {input_tokens, output_tokens, cost}`.
  - Errors 400, 401, 402, 403, 404, 413, 429, 500, 502, 503, 524, 529 as `{error: {code,
    message, metadata?}}`. Context "32,000 tokens. That's the `state` you send plus the
    questions." Pricing: input tokens only ("Output tokens are free").
  - Provider slug from `GET /api/v1/models/typesafe/jev-1.13/endpoints`: `tag: "typesafe"`
    (DeepSeek `deepseek`, Z.AI `z-ai`).
  - Built from this: `jev.role_transport`.

## R3 · Google Document AI (statement PDFs, backend `document_ai`) — `extract/document_ai.py`

- Question: how to send a PDF to a processor and where the tables come back.
- The human docs (`cloud.google.com` → `docs.cloud.google.com`) were denied by the build
  session's network policy on 2026-10-01. Read instead, the same day: Google's official
  machine-readable description of the API, the Discovery document
  `https://documentai.googleapis.com/$discovery/rest?version=v1` ("Cloud Document AI API",
  `v1`, revision `20260915`).
- Quotes:
  - `documentai.projects.locations.processors.process`: `POST` `v1/{+name}:process`,
    "Processes a single document." `name`: "Format:
    `projects/{project}/locations/{location}/processors/{processor}`, or
    `…/processors/{processor}/processorVersions/{processorVersion}`". Scope
    `https://www.googleapis.com/auth/cloud-platform`.
  - `ProcessRequest`: `rawDocument` "A raw document content (bytes)"; `skipHumanReview`
    "Whether human review should be skipped for this request. Default to `false`."
    `RawDocument`: `content` (format `byte`) "Inline document content", `mimeType` "An IANA
    MIME type".
  - `ProcessResponse.document`; `Document.text` "UTF-8 encoded text in reading order";
    `Document.pages[].tables[]` "A table representation similar to HTML table structure"
    with `headerRows` / `bodyRows` → `cells`; `TableCell.colSpan` "How many columns this cell
    spans", `rowSpan` "How many rows this cell spans", `layout.textAnchor`.
  - `TextAnchor.content` "Contains the content of the text span so that users do not have to
    look it up in the text_segments"; `TextSegment.startIndex` / `endIndex` "TextSegment
    start / half open end UTF-8 char index in the Document.text".
  - `Document.error` "Any error that occurred while processing this document";
    `shardInfo.shardCount` "Total number of shards"; `revisions[].processor` "identify the
    processor by its resource name".
  - `endpoints`: regional, e.g. location `eu` → `https://documentai.eu.rep.googleapis.com/`
    (also `us`, `europe-west2`, `europe-west3`, `asia-south1`, `asia-southeast1`,
    `northamerica-northeast1`, `australia-southeast1`).
- Read as: a "char index" is a character (code point) index into `text`; the code prefers
  `textAnchor.content` when present. A misread offset shows as cells that do not parse or
  lines that do not tie to the header balances; both refuse the statement.
- Auth: `google-auth` 2.59.1, read from the installed source:
  `service_account.Credentials.from_service_account_info(info, scopes=…)`, `.refresh(request)`
  with `google.auth.transport.urllib3.Request`, `.valid`, `.token`; `google.auth.default()`
  reads `GOOGLE_APPLICATION_CREDENTIALS` first.
- Not read (owner's choice, recorded open in BUILD): which processor type returns
  `pages[].tables` for these statements; the processor's location (EU recommended).

## R4 · OpenRouter: chat, provider data policies, key spend, the free tier — `explain.py`, `provider_policy.py`

- Question: how System Two is sent through OpenRouter, how a provider's data policy is known
  and enforced, how each key's spend is read, and what the pinned models do in practice.
- Official URLs: https://openrouter.ai/docs/guides/routing/provider-selection,
  https://openrouter.ai/docs/guides/features/sovereign-ai (read 2026-10-03). Most points below
  are **observed** on 2026-10-03 from OpenRouter's own answers to this service (quoted), not
  from documentation; each is marked so.
- Chat: `POST https://openrouter.ai/api/v1/chat/completions` with `provider: {only: [...],
  allow_fallbacks: false, data_collection: "deny"}`. A pin whose provider trains on prompts is
  refused, observed: HTTP 404 "No endpoints found matching your data policy (Paid model
  training)". The code reads 404 + "data policy" as `PolicyRefused` (L32).
- Provider data policies, observed: `GET https://openrouter.ai/api/frontend/v1/all-providers`
  carries `dataPolicy: {training, retainsPrompts}` per provider (a front-end endpoint, not in
  the API reference). A provider passes when both are false; 52 of 92 passed on 2026-10-03.
- Spend per key, observed: `GET /api/v1/key` with the key itself → `usage`, `usage_daily`,
  `usage_weekly`, `usage_monthly`, `limit`, `limit_remaining`, `limit_reset`, `is_free_tier`,
  `label` (`label` can show part of the key: never passed on). A management key reads
  `GET /api/v1/credits` and `GET /api/v1/keys`.
- The free tier, observed: while the account had never bought credits (`is_free_tier: true`),
  each request was capped by what the free pool could pay, whatever the key's own limit:
  HTTP 402 "This request requires more credits, or fewer max_tokens. You requested up to 6000
  tokens, but can only afford 4137." Buying credits set `is_free_tier: false` on every key and
  the cap went.
- `z-ai/glm-5.3` on Z.AI, observed: reasoning cannot be turned off (HTTP 400 "Reasoning is
  mandatory for this endpoint and cannot be disabled"), so the code sends `reasoning: {effort:
  "low", exclude: true}` with `max_tokens` 6000. Its JSON answer sometimes comes wrapped as
  `{"answer": {...}}` or `{"answer": "<the JSON as a string>"}`, and it may cite an empty list
  as a fact; English answers had fewer slips than Romanian ones.
- `moonshotai/kimi-k2.6` on Moonshot AI, observed (6 tries): with no `reasoning` field it wrote
  only reasoning and an empty answer 5 times, ~139 s and ~$0.02 a call.
- Railway's edge closes a request at 300 s (observed HTTP 499 from the edge): a long model
  comparison must be split into single calls.
- EU in-region routing (docs): `https://eu.openrouter.ai/api/v1` on the Business and Enterprise
  plans only, "decrypted within the designated region and routed only to provider endpoints in
  that region". Observed with `GET /api/v1/models?region=eu`: 70 models, `z-ai/glm-5.3` (on
  Inceptron, Mistral) and `moonshotai/kimi-k2.6` (Inceptron) among them; Jev is not listed
  (it is on the Decisions endpoint, R2). The EU decision itself is WP-D4.

## R5 · SAGA WEB API, Claude in Chrome, Firebird drivers — the "Claude Code access to SAGA" note

- Question: an owner's working note (2026-10-03, not in this repo) proposed giving Claude Code
  access to SAGA through SAGA WEB's API and Claude in Chrome, else a Firebird copy of SAGA C.
  What do the official pages say, and what may this system take from it?
- Official URLs, read 2026-10-03: https://web0.sagasoft.ro/sagac/DocumentatieAPI,
  https://code.claude.com/docs/en/chrome, https://pypi.org/project/firebird-driver/ (2.0.3),
  https://pypi.org/project/fdb/ (2.0.4), https://pypi.org/project/windows-mcp/ (0.8.7).
  Not read (refused): forum.sagasoft.ro (thread t=60757), https://web.sagasoft.ro/test/Firme,
  github.com/danieleteti/mcp-firebird. So SAGA C's default Firebird password, "ODS 12 since
  3.0.583" and the test tenant stay `[de confirmat]`.
- SAGA WEB API (`https://web.sagasoft.ro/api/v20260225/`), quotes:
  - Three calls: `Import` (POST, multipart/form-data), `Situatii/GetStocArticol` (GET,
    `codArticol` required, `gestiune`, `data` "in format dd.MM.yyyy (orice alt format va returna
    o eroare)"), `Situatii/GetSituatieStocuri` (GET, `dataStart`, `dataEnd`; HTTP 200 is the XML
    file, otherwise JSON `{Success, Message}`). The section "Preluare sold conturi" repeats the
    `Import` URL: no balance read exists. No read of journal, invoices, partners or balance.
  - Import is staged: "Pentru finalizarea importului, trebuie sa accesati ecranul Diverse →
    Import date din Saga Web." The upload answers only `{Success, Message}`.
  - Auth: `Authorization: Bearer <key>` and `X-Saga-Cod-Fiscal: <cif>`. Key: "Utilizatori →
    Integrare API → Genereaza cheie de acces"; "Ecranul "Integrare API" poate fi accesat doar de
    utilizatori de tip Admin." Rotation: "In anumite situatii, raspunsul va contine … o noua
    cheie de acces in header-ul X-Saga-Refresh-Token. Aceasta trebuie salvata … In caz contrar,
    cheia de acces va fi blocata."
  - File names as SAGA C (R1): `F_`, `I_`, `P_`, `CLI_`, `FUR_`, `ART_`, plus `C_` (comenzi).
    Every tag `sinks/saga_xml.py` writes is on the page. Optional tags not in R1: `FacturaTip`
    values (" " factură, "A" aviz, "B" bon de casă, "T" taxare inversă, "C" bon de casă cu cod
    fiscal), `FacturaIndexDescarcareSPV` ("ID-ul recipisei e-Facturilor"), a partner `Cod`
    ("codul de client sau furnizor din Saga"), `TipDeducere` on purchase lines ("N50" 50 %,
    "I" nedeductibil). dd.MM.yyyy is stated for query parameters only, not for XML tags.
- Claude in Chrome, quotes: extension "version 1.0.36 or later"; "A direct Anthropic plan (Pro,
  Max, Team, or Enterprise)" and `/login` (off with an API key, `setup-token`, Bedrock or
  Vertex); "isn't supported in Windows Subsystem for Linux (WSL)"; uploads "up to 10 MB"; it
  "shares your browser's login state, so it can access any site you're already signed into";
  "In auto mode, when the auto mode classifier itself approves a browser call to a site, the
  extension skips its own per-site check for that call, unless your permission rules deny any
  site to Claude in Chrome."
- Firebird drivers: `fdb` is "LEGACY … Firebird version 2.5, with limited support for Firebird
  3.0. It does NOT support Firebird 4 and newer"; `firebird-driver` "Requires: Firebird 3+".
  Its `connect()` takes no client-library argument: the library is set with
  `driver_config.fb_client_library.value` before connecting (read in the 2.0.3 wheel).
- Code takes: nothing yet. Tags stay R1's until a copy-firm import proves more (AGENTS).
  Claude Code or Claude in Chrome never touches a client's firm (L33, L35); mouths stay
  deterministic (§1). SAGA C is tested first (`docs/owner/COPY_FIRM_TEST.md` §1–§10); SAGA WEB as a
  mouth would be a sink-product change (a dated amendment), only once a client is on it. Open
  for Saga: does one key reach every firm of the account, does a new key end the old one, can
  a key belong to a non-Admin user, does the web finish screen keep sync "Nr.+data".

## R6 · The EU route per model family: options, prices, LangSmith — WP-D4

- Question: where each model role could serve client data in the EU, at what price, and whether
  LangSmith helps. Read 2026-10-03 for the owner; the decision stays WP-D4 (`BUILD.md`).

Research of 2026-10-03 (sources below). Until the owner decides, every role keeps `eu_route: null`
and a client tenant is refused by every model role (Jev: cautious values and a person; System
Two: the question without an explanation; reading: the statement's tables must be sent).

- **Document reading (Gemini) → Vertex AI, EU multi-region `eu`.** Every model the catalog pins
  (`gemini-3.5-flash-lite`, `-3.1-flash-lite`, `-3.8-flash`, `-3.7-flash`; reserve `-3.5-flash`,
  `-3.6-flash`) is GA on the `eu` multi-region, which Google ties to EU ML processing; a
  regional endpoint alone does not guarantee it. Zero retention: turn off caching and get the
  abuse-monitoring exception (invoiced billing) or an enterprise ZDR contract
  (`docs/owner/EU_VERTEX_SETUP.md` §D). Code: `EU_LOCATIONS["vertex"]` lacks `eu`; no Vertex transport.
- **System Two (GLM) — two candidates:**
  - **Scaleway Generative APIs, `glm-5.2`** (one version behind the `z-ai/glm-5.3` pin; also
    `deepseek-v4-flash-0731`). Paris; zero data retention by default; no training; a French
    company, outside the US CLOUD Act; OpenAI-compatible chat. Caveats: an automatic cache of
    intermediate values (not prompt text) that cannot be turned off; the full request may be
    kept up to 2 weeks after a server error (500).
  - **OpenRouter EU in-region (`https://eu.openrouter.ai/api/v1`), `z-ai/glm-5.3`** on Mistral or
    Inceptron (Kimi K2.6 on Inceptron). Keeps the current pin and sender, but needs OpenRouter's
    Business or Enterprise plan (price from sales), and OpenRouter, Inc. (US) stays in the chain.
- **System One (Jev): no EU route.** `typesafe/jev-1.13` is served only by TypeSafe AI, Inc. (US;
  operated from the US West Coast per third-party listings; its DPA names no location and uses
  EU SCC Module 2). Zero data retention for enterprise customers on request. It is not on
  OpenRouter's EU list. Options: (a) no Jev on client data, its decisions go to a person (how the
  code behaves today); (b) change L33 to allow TypeSafe under SCCs plus an enterprise ZDR
  contract and a transfer assessment; (c) an EU model in System One's place for client data,
  evaluated against Jev on synthetic data first.

Sources: Scaleway supported models (validated 2026-08-14) and Generative APIs data privacy
(`github.com/scaleway/docs-content`, `pages/generative-apis/reference-content/`); OpenRouter
sovereign AI guide (`openrouter.ai/docs/guides/features/sovereign-ai`) and its models API with
`region=eu` / `eu.openrouter.ai` (read 2026-10-03: 70 EU-eligible models); TypeSafe legal and
DPA (`docs.typesafe.ai/legal`, `typesafe.ai/legal/data-processing`); Gemini EU listings
(`opper.ai/models/eu/gemini`) and Google's data residency page (not readable from the session).

**Pricing, read 2026-10-03** (per million tokens, before tax; EUR → USD at the ECB rate of
2026-10-02, 1 EUR = 1.1225 USD):

| Role / model | OpenRouter (the pinned provider) | Scaleway serverless, Paris |
|---|---|---|
| System Two `z-ai/glm-5.3` on Z.AI (alternate: same on Together) | $1.40 in / $4.40 out | not served |
| nearest on Scaleway: `glm-5.2` | Z.AI $1.40 / $4.40 | €1.80 / €5.50 (≈ $2.02 / $6.17); batch €0.90 / €2.75 (≈ $1.01 / $3.09) |
| System Two alternate `moonshotai/kimi-k2.6` on Moonshot | $0.95 / $4.00 | not served |
| System One `typesafe/jev-1.13` on TypeSafe | $0.042 / $0 | not served |
| Document reading (Gemini, direct on Google AI Studio) | — | not served |
| `deepseek-v4-flash` (dropped: its OpenRouter provider trained on prompts) | $0.09 / $0.18 (DeepInfra) to $0.44 / $1.32 (Cloudflare) | €0.40 / €0.80, cached €0.08 |

- Per System Two explanation (≈ 1,550 input / 610 output tokens, the live sample of 2026-10-03):
  OpenRouter ≈ $0.0049 at list price (≈ $0.0042 as billed for those 5 calls); Scaleway live
  ≈ $0.0069 (about 1.4×); Scaleway batch ≈ $0.0035 (about 30 % below OpenRouter).
- OpenRouter: "no markup on inference pricing (however we do charge a fee when purchasing
  credits)" — the percentage was not on the FAQ page. Its EU in-region route
  (`eu.openrouter.ai`) needs a Business or Enterprise plan, priced on request.
- Scaleway: "You benefit from a free tier on the first 1,000,000 tokens" (reads as once per
  account); "All requests performed using Batches API are priced with a -50% discount".
- Scaleway Batches API (how-to validated 2026-02-17; FAQ): a JSONL file in an Object Storage
  bucket of the same project, one model per file ("The `method`, `url`, and `model` fields must
  remain consistent across all requests"); "We aim to process any batch within 24 hours.
  After this delay, batch processing will be stopped, and any remaining unprocessed queries
  will not be billed"; no rate limit. No model is excluded from batching in the docs, but none
  names `glm-5.2` either: **[de confirmat]** with one small test batch (no Scaleway key in the
  build sessions).
- Owner, 2026-10-03: with several clients, System Two's explanations could be batched on
  Scaleway (EU, Paris), bringing its cost below OpenRouter's. What that implies:
  - only System Two moves: Jev and Gemini are not on Scaleway, and Jev's `v3_judge` sits on the
    path to every approval, so a 24-hour wait there would stall the flow;
  - an explanation arrives up to 24 hours after its question (e.g. a nightly batch for the
    questions still waiting); until then the question shows without one, as today when none
    comes back;
  - requests a batch drops after 24 hours are sent again or left unexplained;
  - input and output pass through our own Scaleway bucket: deleting them after each batch is
    ours; Scaleway may keep a full request up to 2 weeks after a server error (above);
  - `glm-5.2` reasons at `max` by default: each line sets low effort, as the current sender
    does; and it is one version behind the GLM 5.3 pin, so it is compared with it on the
    synthetic questions first (`POST /model-roles/{role_id}/compare`).

Sources (2026-10-03): `openrouter.ai/api/v1/models/{model}/endpoints`, `openrouter.ai/docs/faq`;
`scaleway.com/en/pricing/model-as-a-service/`; `github.com/scaleway/docs-content`
`pages/generative-apis/` (`faq.mdx`, `concepts.mdx`, `how-to/use-batch-processing.mdx`);
`ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml`.

**LangSmith (tracing and evaluation), read 2026-10-03** — the owner asked whether to use it,
host it on Railway, migrate to it, and use its EU option on client data.

- Self-hosting: "Self-hosted LangSmith is an add-on to the Enterprise plan … Contact our sales
  team if you want to get a license key". It installs on Kubernetes (Helm) with ClickHouse
  (traces), PostgreSQL, Redis and blob storage. Railway is not Kubernetes, and a single VPS
  would mean running a cluster for an Enterprise product: in practice it is LangChain's cloud
  or an Enterprise contract. LangGraph itself (open source) stays on Railway either way.
- Cloud plans: Developer $0 (1 seat, 5k base traces a month), Plus $39 per seat (10k base
  traces), Enterprise custom ("Self-hosted and hybrid deployment options"). Base traces are
  kept 14 days, extended traces 180 days (extra fee).
- EU: "organizations on https://eu.smith.langchain.com are in GCP EU"; regional instances on
  all plans, free included; "pricing is the same across supported cloud regions"; paid in USD.
  GDPR, SOC 2 Type 2, a DPA on request. But: "We do not have a legal entity in the EU for
  customer contracting today" — a US contracting party, the same concern as OpenRouter above.
- Migrating what is built: not worth it. The answer log (who answered, append-only), the
  model-call record (role, pin, card hash, synthetic guard), the catalog, gates, scenarios and
  coverage map are the system's record and law, kept in our Postgres; a trace store with
  14 / 180-day retention does not replace them. What LangSmith adds is side-by-side model
  evaluation (better than `POST /model-roles/{role_id}/compare`) and a run-by-run trace view:
  an addition, not a migration.
- Client data: a trace holds the whole document (CUIs, amounts, partners), so LangSmith would be
  a new place client data goes — under L33 a dated change of law, a DPA and a
  transfer assessment. Little gain for explanations (what each model was given and answered,
  under which card, and what the person decided are already recorded; its online scoring
  would be another model reading client data, and its annotation queues a second review
  surface beside the review page, which L26 keeps free of outside services). More gain if
  multi-step AI work on client data is built later: decide it then, with this WP, against a
  self-hostable open-source tracing tool on our own EU hosting (not checked yet).
- Recommendation (2026-10-03): migrate nothing now. If the WP-D4 model evaluations want it
  (Scaleway `glm-5.2`, Kimi, an EU model in Jev's place), the hosted EU free tier on synthetic
  data only, fed from `fixtures/scenarios/`: no amendment, no migration.

Sources (2026-10-03): `docs.langchain.com/langsmith/self-hosted`,
`docs.langchain.com/langsmith/regions-faq`, `www.langchain.com/pricing`.
