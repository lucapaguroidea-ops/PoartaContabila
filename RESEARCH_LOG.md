# Research log

Rule (`annex/GROK_BOT_BRIEF_RO_ACCOUNTING_LOOP.md` §5): never guess an external format or API.
Each item names the question, the official URL, a short quote, the date it was read, and what
the code takes from it. A page that cannot be read gives nothing to build: the code keeps a
typed stub that refuses (fail closed) and the item says what the owner must do.

## R1 · SAGA C "Import date": invoices, receipts, payments, nomenclatures — WP-03, WP-19

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
- Code takes: WP-03 and WP-19 write only tags listed above (`sinks/saga_xml.py`: invoices;
  receipts and payments without `ContClient` / `ContFurnizor` / `Moneda`).

## R2 · Jev (TypeSafe AI System One) API — WP-20

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
- What WP-20 takes from this (not built yet, see BUILD WP-20): `POST {JEV_BASE_URL}/v1/systemone`
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
  - Built from this: WP-20 (`jev.role_transport`).

## R3 · Google Document AI (statement PDFs, backend `document_ai`) — WP-21

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
