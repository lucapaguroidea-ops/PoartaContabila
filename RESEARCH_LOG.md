# Research log

Rule (`annex/GROK_BOT_BRIEF_RO_ACCOUNTING_LOOP.md` §5): never guess an external format or API.
Each item names the question, the official URL, a short quote, the date it was read, and what
the code takes from it. A page that cannot be read gives nothing to build: the code keeps a
typed stub that refuses (fail closed) and the item says what the owner must do.

## R1 · SAGA C receipts / payments XML import (`incasare_xml`, `plata_xml`) — WP-19

- Question: file name, root and child tags, value formats of the receipts and payments XML
  import (`P_<data>.xml`, root `<Plati>`, and any receipts counterpart).
- Official URL: https://manual.sagasoft.ro/sagac/topic-76-import-date.html
- 2026-10-01: **not read.** The build session's network policy denied the host
  (`CONNECT` refused by the egress proxy, both by direct fetch and by the web fetcher).
- Quote: none. Nothing about the bank layout is built; no `fixtures/saga/incasare.xml` or
  `plata.xml` exists. Bank lines still stop at `needs_human` ("post it in SAGA").
- Instruct: allow `manual.sagasoft.ro` in the environment's network access, then rerun WP-19.

## R2 · Jev (TypeSafe AI System One) API — WP-20

- Question: endpoint, authentication, request body (how a pack's questions are sent), response
  shape (how Choice / Score / Noul answers come back), timeouts, error codes, model pinning.
- Official URLs: https://docs.typesafe.ai/api.md, https://docs.typesafe.ai/primitives.md,
  https://docs.typesafe.ai/sdk/python/usage.md, https://docs.typesafe.ai/models.md
- 2026-10-01: **not read.** The host was denied by the build session's network policy.
- Quote: none. What was built does not depend on the wire: closed output models from
  ARCHITECTURE §12, the `(pack, input_hash)` cache, fail closed, the graph nodes.
  `jev.http_transport` refuses every call (`JevNotDocumented`) so nothing is sent and a person
  is asked. Still to take from the docs: the request/response wire, and how Jev's primitives
  map onto `V3Judge` (`accounts_ok`, `risk` low/medium/high, `needs_human`) and `V2Gate`.
- Instruct: allow `docs.typesafe.ai` in the environment's network access, then finish WP-20.
  `JEV_BASE_URL` / `JEV_API_KEY` are not set on Railway; the owner adds them.

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
