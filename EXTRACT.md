# Extract adaptor

WP-02 / WP-13. One contract for every backend (`ubl`, `mt940`, `document_ai`, `gemini`, `docling`).

Under the source object's bucket prefix:

```
normalized/markdown.md      text the graph may read
normalized/tables.json      list of {headers, rows} as strings
normalized/extract_meta.json
```

`extract_meta.json`:

```
{
  "backend": "document_ai|gemini|ubl|mt940|docling|none",
  "source_hash": "...",
  "model_or_version": "...",
  "needs_ocr": false,
  "identity_ok": true
}
```

Rules:

- XML first (A2): when a document exists as XML (UBL CIUS-RO, EU e-invoice), parse the XML → CanonicalDocument fields; never OCR or parse a PDF of the same document. In SPV zips, `semnatura_*.xml` is the signature companion.
  Code: `poarta_contabila/extract/ubl.py` — `read_spv_zip` (members split by root element), `parse_ubl` (totals checked, fail closed), `to_canonical` (tenant side, signed storno). Unit codes (`H87`, `C62`) reach SAGA unmapped until `maps` covers them.
- `skip_if: [has_text_layer, is_ubl]` is on the SourceDoc row.
- Graph state stores field strings, not raw model JSON.
- Swap Docling later without changing node names. Same three files.
- Statement PDFs of synthetic tenants are read by Gemini through Google AI Studio (`extract/gemini.py`, WP-36; tiers and waiting: 00_LAW §8 A4–A6); a client tenant's needs the EU route (WP-D4).
- extras PDF uses `document_ai` until WP-13. It does not emit a Job per statement total. See `catalog/60_harvest/ARTICOLE_EXTRAS_GRAIN_v1.yaml`.
  Code (WP-21): `poarta_contabila/extract/document_ai.py` (the reader, from the API's Discovery document) and `extract/contract.py` (the three files, once per `(source_hash, backend)` in `domain.extracts`).
