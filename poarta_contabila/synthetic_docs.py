"""Synthetic documents for tests and evaluations: real PDFs of invented data (no client data).

``text_pdf`` writes a plain PDF (Courier, one text line per printed line, no images, no
timestamps), so the same input gives the same bytes on every run: a rerun finds the same
Job or stored extract instead of minting or reading again.
"""

from __future__ import annotations

PAGE_LINES = 52  # lines that fit an A4 page at 9 pt with 14 pt leading


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_pdf(pages: list[list[str]]) -> bytes:
    """A real PDF of *pages*, each a list of printed lines (latin-1 only)."""
    if not pages:
        raise ValueError("a PDF needs at least one page")
    n_pages = len(pages)
    first_page = 4  # 1 catalog, 2 pages, 3 font; then (page, content) pairs
    kids = " ".join(f"{first_page + 2 * i} 0 R" for i in range(n_pages))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]
    for i, lines in enumerate(pages):
        if len(lines) > PAGE_LINES:
            raise ValueError(f"page {i + 1} has {len(lines)} lines; at most {PAGE_LINES} fit")
        shown = " ".join(f"({_escape(line)}) '" for line in lines)
        stream = f"BT /F1 9 Tf 14 TL 40 800 Td {shown} ET".encode("latin-1")
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {first_page + 2 * i + 1} 0 R >>"
            ).encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)
