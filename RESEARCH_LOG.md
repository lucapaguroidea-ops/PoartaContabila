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
- Code takes: WP-03 writes only tags listed above (`sinks/saga_xml.py`); WP-19 builds the
  receipts and payments mouths from this item.

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
