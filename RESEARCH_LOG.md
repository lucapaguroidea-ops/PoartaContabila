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
