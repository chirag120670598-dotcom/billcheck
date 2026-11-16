"""Getting a table out of a PDF without losing its shape.

The naive call is ``page.extract_text()``, and for an invoice it produces this:

    Sr
    Description
    HSN/SAC
    Qty
    ...
    1
    Cotton Fabric 40s
    5208
    120
    450.00

Every column on its own line. The information is all there and completely
useless, because nothing tells you that "120" is a quantity rather than a rate.

The fix is to stop asking for text and start asking for *positions*. PDF text is
drawn at coordinates, so each fragment carries an x and a y. Fragments that share
a y (within a tolerance) are on the same visual line; sorting them by x rebuilds
the row. That is the whole trick, and it is what makes the difference between a
tool that reads invoices and a tool that reads the word "invoice" a lot.

Scope, stated plainly: this reads PDFs that contain a text layer. A photograph
or a scan of a bill has no coordinates to read, and is refused with a clear
message rather than silently returning nothing.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

__all__ = ["Row", "Document", "read_pdf", "rows_from_text", "read_any",
           "PdfUnavailable", "NoTextLayer"]

#: Two fragments whose baselines are within this many points are one row.
#: A line of 9pt text sits about 11pt apart from the next, so 3 is comfortable.
DEFAULT_TOLERANCE = 3.0

#: PDF pages sometimes draw a character at a time. Fragments this far apart
#: horizontally with no space between them are still separate cells only if the
#: gap is real -- so we join fragments whose x distance is under this.
_JOIN_GAP = 1.5


class PdfUnavailable(RuntimeError):
    """pypdf is not installed."""


class NoTextLayer(ValueError):
    """The document has no extractable text -- it is a scan or an image."""


@dataclass
class Row:
    """One visual line, as cells sorted left to right."""

    y: float
    cells: List[str] = field(default_factory=list)
    xs: List[float] = field(default_factory=list)
    page: int = 0

    @property
    def text(self) -> str:
        return " ".join(self.cells)

    def __len__(self) -> int:
        return len(self.cells)

    def __iter__(self):
        return iter(self.cells)

    def __getitem__(self, index):
        return self.cells[index]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Row(y={self.y:.1f}, {self.cells})"


@dataclass
class Document:
    source: str
    rows: List[Row] = field(default_factory=list)
    page_count: int = 0

    @property
    def text(self) -> str:
        return "\n".join(row.text for row in self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)


def _require_pypdf():
    try:
        import pypdf  # noqa: F401
        return pypdf
    except ImportError as error:  # pragma: no cover - depends on environment
        raise PdfUnavailable(
            "reading PDFs needs pypdf. Install it with: pip install pypdf"
        ) from error


def _fragments(page) -> List[tuple]:
    """Every non-empty text fragment on a page, as (y, x, text)."""
    out: List[tuple] = []

    def visitor(text, cm, tm, font_dict, font_size):
        if text is None:
            return
        stripped = text.strip()
        if not stripped:
            return
        try:
            x = float(tm[4]) if tm[4] is not None else 0.0
            y = float(tm[5]) if tm[5] is not None else 0.0
        except (TypeError, IndexError):
            return
        out.append((y, x, stripped))

    page.extract_text(visitor_text=visitor)
    return out


def _build_rows(fragments: Sequence[tuple], tolerance: float, page_number: int) -> List[Row]:
    """Cluster fragments into rows, top of the page first."""
    if not fragments:
        return []

    ordered = sorted(fragments, key=lambda item: (-item[0], item[1]))
    clusters: List[List[tuple]] = []
    for fragment in ordered:
        if clusters and abs(clusters[-1][0][0] - fragment[0]) <= tolerance:
            clusters[-1].append(fragment)
        else:
            clusters.append([fragment])

    rows: List[Row] = []
    for cluster in clusters:
        cluster.sort(key=lambda item: item[1])
        cells: List[str] = []
        xs: List[float] = []
        last_x: Optional[float] = None
        last_text = ""
        for y, x, text in cluster:
            # Fragments drawn one character at a time land at almost the same
            # x. Joining them rebuilds the word; not joining turns "Invoice"
            # into seven cells and breaks every column count downstream.
            if cells and last_x is not None and 0 <= x - (last_x + len(last_text) * 0.1) < _JOIN_GAP:
                cells[-1] = cells[-1] + text
                last_text = cells[-1]
            elif cells and last_x is not None and abs(x - last_x) < _JOIN_GAP:
                cells[-1] = cells[-1] + " " + text
                last_text = cells[-1]
            else:
                cells.append(text)
                xs.append(x)
                last_x = x
                last_text = text
        rows.append(Row(y=cluster[0][0], cells=cells, xs=xs, page=page_number))
    return rows


def read_pdf(path: str, *, tolerance: float = DEFAULT_TOLERANCE) -> Document:
    """Read a text-layer PDF into positional rows."""
    pypdf = _require_pypdf()
    try:
        reader = pypdf.PdfReader(path)
    except Exception as error:
        raise ValueError(f"could not open {path} as a PDF: {error}") from error

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as error:  # pragma: no cover - depends on the file
            raise ValueError(f"{path} is encrypted and cannot be read") from error

    rows: List[Row] = []
    for page_number, page in enumerate(reader.pages, start=1):
        fragments = _fragments(page)
        rows.extend(_build_rows(fragments, tolerance, page_number))

    if not rows:
        raise NoTextLayer(
            f"{path} has no text layer. It is probably a scan or a photo. "
            "billcheck reads digital invoices; a scanned bill needs OCR first."
        )
    return Document(source=path, rows=rows, page_count=len(reader.pages))


def rows_from_text(text: str) -> List[Row]:
    """Build rows from plain text that already has one record per line.

    Used for tests, for .txt exports, and for invoices pasted out of a mail.
    Cells are split on two or more spaces, which is what a fixed-width export
    actually produces.
    """
    rows: List[Row] = []
    for index, line in enumerate((text or "").splitlines()):
        if not line.strip():
            continue
        cells = [cell.strip() for cell in re.split(r"\s{2,}|\t", line.strip()) if cell.strip()]
        rows.append(Row(y=float(-index), cells=cells, xs=[], page=1))
    return rows


def read_any(path: str) -> Document:
    """Read a PDF or a text file, whichever it is."""
    if not os.path.exists(path):
        # Raised here rather than deep inside the PDF library, so the message
        # says "no such file" instead of a traceback about a document stream.
        raise FileNotFoundError(path)
    lowered = path.lower()
    if lowered.endswith(".pdf"):
        return read_pdf(path)
    if lowered.endswith((".txt", ".text", ".csv", ".tsv")):
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()
        return Document(source=path, rows=rows_from_text(content), page_count=1)
    raise ValueError(f"unsupported file type: {path}. Use a PDF or a text file.")
