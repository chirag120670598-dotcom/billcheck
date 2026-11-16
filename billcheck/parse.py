"""Reading an invoice out of rows.

Three jobs, in order: find the header fields, find the line-item table, find the
totals. Each one is a search through the same list of rows, and each one is
allowed to fail without taking the others down. A invoice missing its total is
still worth reading -- it just gets a failed check later.

Design rule: **never invent a value.** If the parser cannot find the invoice
total, `invoice.total` is None and a check says so. A parser that guesses is a
parser whose errors are invisible, and an invoice tool whose errors are
invisible is worse than a spreadsheet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .gst import GSTIN_PATTERN, gstin_state_code, state_code_from_name
from .money import is_numeric_cell, normalise_digits, parse_amount, words_to_amount
from .pdf import Document, Row

__all__ = ["Invoice", "ParsedLine", "parse_invoice", "parse_rows",
           "to_iso_date", "HEADER_WORDS"]

#: Words that identify the line-item table header. Two of these on one row is
#: enough, because a row containing "Description" and "Qty" is not a line item.
HEADER_WORDS = {
    "description": ("description", "particulars", "item", "product", "goods",
                    "services", "narration"),
    "hsn": ("hsn", "sac", "hsn/sac", "hsn code"),
    "qty": ("qty", "quantity", "qnty"),
    "rate": ("rate", "price", "unit price"),
    "taxable": ("taxable", "taxable value", "amount", "value", "net"),
    "gst": ("gst%", "gst", "tax%", "rate%", "tax rate", "gst rate"),
}

#: Labels that mark the start of the totals block, which is where the line-item
#: table ends.
_TOTAL_LABELS = (
    "taxable value", "total taxable", "sub total", "subtotal", "cgst", "sgst",
    "igst", "cess", "round off", "roundoff", "total", "grand total",
    "invoice total", "amount payable", "amount in words",
)

#: A GST tax rate. Anything else that looks like a percentage is a column
#: heading, a discount, or noise.
_VALID_GST_RATES = {0, 0.25, 1, 1.5, 2.5, 3, 5, 6, 12, 18, 28}

_DATE_FORMATS = (
    r"(?P<day>\d{1,2})[\s\-/\.]+(?P<month>[A-Za-z]{3,9}|\d{1,2})[\s\-/\.]+(?P<year>\d{4})",
    r"(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})",
)

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


@dataclass
class ParsedLine:
    serial: str = ""
    description: str = ""
    hsn: str = ""
    qty: Optional[object] = None
    rate: Optional[object] = None
    taxable: Optional[object] = None
    gst_rate: Optional[object] = None
    cgst: Optional[object] = None
    sgst: Optional[object] = None
    igst: Optional[object] = None
    raw: List[str] = field(default_factory=list)

    @property
    def tax(self):
        """Total tax on this line, from whichever components are present."""
        parts = [p for p in (self.cgst, self.sgst, self.igst) if p is not None]
        return sum(parts) if parts else None

    def to_dict(self) -> dict:
        from .money import to_decimal
        def num(value):
            converted = to_decimal(value)
            return str(converted) if converted is not None else None
        return {
            "serial": self.serial,
            "description": self.description,
            "hsn": self.hsn,
            "qty": num(self.qty),
            "rate": num(self.rate),
            "taxable": num(self.taxable),
            "gst_rate": num(self.gst_rate),
            "tax": num(self.tax),
        }


@dataclass
class Invoice:
    source: str = ""
    supplier_name: str = ""
    supplier_gstin: str = ""
    buyer_name: str = ""
    buyer_gstin: str = ""
    number: str = ""
    date: str = ""
    place_of_supply: str = ""
    lines: List[ParsedLine] = field(default_factory=list)
    taxable_value: Optional[object] = None
    cgst: Optional[object] = None
    sgst: Optional[object] = None
    igst: Optional[object] = None
    cess: Optional[object] = None
    round_off: Optional[object] = None
    total: Optional[object] = None
    words: str = ""
    words_amount: Optional[object] = None
    #: Fields the parser looked for and did not find. Reported, not hidden.
    missing: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True when nothing that looks like an invoice was found.

        A blank file, a photo, a page of prose: all of these come back with no
        number, no GSTIN, no lines and no totals. Saying "the supplier's GSTIN is
        invalid" about a file that contains no invoice is blaming the wrong
        thing, so this flag lets the report say what actually happened.
        """
        return not any((
            self.supplier_gstin, self.buyer_gstin, self.number, self.date,
            self.lines, self.taxable_value, self.total, self.words,
        ))

    @property
    def date_iso(self) -> str:
        """The invoice date as YYYY-MM-DD, or "" if it could not be read."""
        return to_iso_date(self.date)

    @property
    def all_gstins(self) -> List[str]:
        return [g for g in (self.supplier_gstin, self.buyer_gstin) if g]

    @property
    def supplier_state(self) -> Optional[str]:
        return gstin_state_code(self.supplier_gstin)

    @property
    def supply_state(self) -> Optional[str]:
        return state_code_from_name(self.place_of_supply)

    @property
    def tax_excluding_cess(self):
        """CGST + SGST + IGST. Cess has its own rates and is left out of
        anything that reasons about GST rates."""
        parts = [p for p in (self.cgst, self.sgst, self.igst) if p is not None]
        return sum(parts) if parts else None

    @property
    def claimed_tax(self):
        parts = [p for p in (self.cgst, self.sgst, self.igst, self.cess) if p is not None]
        return sum(parts) if parts else None

    def to_dict(self) -> dict:
        from .money import to_decimal
        def num(value):
            converted = to_decimal(value)
            return str(converted) if converted is not None else None
        return {
            "source": self.source,
            "supplier": {"name": self.supplier_name, "gstin": self.supplier_gstin},
            "buyer": {"name": self.buyer_name, "gstin": self.buyer_gstin},
            "invoice_number": self.number,
            "invoice_date": self.date,
            "invoice_date_iso": self.date_iso,
            "place_of_supply": self.place_of_supply,
            "lines": [line.to_dict() for line in self.lines],
            "totals": {
                "taxable_value": num(self.taxable_value),
                "cgst": num(self.cgst),
                "sgst": num(self.sgst),
                "igst": num(self.igst),
                "cess": num(self.cess),
                "round_off": num(self.round_off),
                "total": num(self.total),
            },
            "amount_in_words": self.words,
            "missing_fields": list(self.missing),
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _label_of(row: Row) -> str:
    return " ".join(row.cells).lower()


#: Words that mark a row as being about the buyer.
BUYER_WORDS = re.compile(r"\b(buyer|recipient|customer|bill\s*to|billed\s*to|consignee)\b",
                         re.IGNORECASE)

#: A GSTIN on a line that is not about the supplier.
_BEFORE_ITEMS = re.compile(r"gstin|gst\s*in|tin", re.IGNORECASE)

#: Anything that starts a new field on the same printed line. Used to stop a
#: value from swallowing the field printed to its right.
_NEXT_FIELD = re.compile(
    r"\s+(?=(?:buyer|recipient|customer|bill\s*to|place\s*of\s*supply|supplier|"
    r"seller|gstin|invoice\s*(?:no|number|date|total)|state\s*code|taxable|"
    r"cgst|sgst|igst|cess|round\s*off|grand\s*total|total|hsn|qty|"
    r"amount\s*in\s*words|payment|terms)\b)",
    re.IGNORECASE)


def _value_after_label(row: Row, label: str) -> Optional[str]:
    """Find the value for a label, whether it is in the next cell or the same one.

    Handles all three shapes seen in the wild:

        ["CGST", "2232.00"]          two cells
        ["CGST:", "2232.00"]         label with a colon
        ["CGST: 2232.00"]            one merged cell
        ["Buyer: Patel Ltd", "Place of Supply: Gujarat (24)"]   two fields, one row

    The last shape is why this cannot simply take everything after the label:
    the buyer's name would run into the place of supply. Cells are tried first
    because they carry the layout, and the joined text is cut at the next field
    name when they do not.
    """
    lowered = label.lower()

    # 1. A cell that is only the label: the value is the next cell.
    for index, cell in enumerate(row.cells):
        if cell.strip().lower().rstrip(":") == lowered:
            if index + 1 < len(row.cells) and row.cells[index + 1].strip():
                return row.cells[index + 1].strip()

    # 2. A cell that begins with the label.
    for cell in row.cells:
        match = re.match(re.escape(label) + r"\s*:?\s*(.+)$", cell.strip(),
                         re.IGNORECASE)
        if match and match.group(1).strip():
            return _cut_at_next_field(match.group(1))

    # 3. The label appears somewhere in a merged cell.
    joined = " ".join(cell.strip() for cell in row.cells)
    match = re.search(re.escape(label) + r"\s*:?\s*(.+)$", joined, re.IGNORECASE)
    if match and match.group(1).strip():
        return _cut_at_next_field(match.group(1))
    return None


def _cut_at_next_field(value: str) -> str:
    """Trim separators from a value without eating its sign.

    ``str.strip(" :-")`` looks right and is not: it strips the leading minus
    from "-0.60", which turned a round-off in the customer's favour into one in
    the supplier's. Only colons and whitespace are trimmed.
    """
    return re.sub(r"^[\s:]+|[\s:]+$", "", _NEXT_FIELD.split(value, maxsplit=1)[0])


def _find_gstin(text: str) -> str:
    match = GSTIN_PATTERN.search(text or "")
    return match.group(1).upper() if match else ""


def _parse_date(text: str) -> str:
    """Return an ISO date when one can be read, else the original text."""
    if not text:
        return ""
    for pattern in _DATE_FORMATS:
        match = re.search(pattern, text)
        if not match:
            continue
        groups = match.groupdict()
        try:
            day = int(groups["day"])
            year = int(groups["year"])
            month_raw = groups["month"]
            month = _MONTHS.get(month_raw.lower()[:9]) if month_raw.isalpha() \
                else int(month_raw)
        except (KeyError, TypeError, ValueError):
            continue
        if month and 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return text.strip()


def _is_header_row(row: Row) -> bool:
    lowered = _label_of(row)
    hits = 0
    for words in HEADER_WORDS.values():
        if any(word in lowered for word in words):
            hits += 1
    return hits >= 2


def _is_totals_row(row: Row) -> bool:
    lowered = _label_of(row)
    return any(lowered.startswith(label) or f" {label}" in f" {lowered}"
               for label in _TOTAL_LABELS)


def _column_map(header: Row) -> Dict[str, int]:
    """Which cell index holds which field, from the header row's own words."""
    mapping: Dict[str, int] = {}
    for index, cell in enumerate(header.cells):
        lowered = cell.lower().strip()
        for field_name, words in HEADER_WORDS.items():
            if field_name in mapping:
                continue
            if any(word in lowered for word in words):
                mapping[field_name] = index
                break
    return mapping


def _numbers(row: Row) -> List[Tuple[int, object]]:
    """(cell index, Decimal) for every cell that is *only* a number."""
    out = []
    for index, cell in enumerate(row.cells):
        if is_numeric_cell(cell):
            value = parse_amount(cell)
            if value is not None:
                out.append((index, value))
    return out


def _looks_like_line_item(row: Row) -> bool:
    """A line item has a description and at least two numbers."""
    numbers = _numbers(row)
    if len(numbers) < 2:
        return False
    if _is_totals_row(row) or _is_header_row(row):
        return False
    # At least one cell that is not a number and not blank: the description.
    text_cells = [c for c in row.cells if not is_numeric_cell(c) and c.strip()]
    return bool(text_cells)


def _build_line(row: Row, columns: Dict[str, int]) -> Optional[ParsedLine]:
    """Turn one row into a line item using the header's column positions."""
    line = ParsedLine(raw=list(row.cells))

    def cell(field_name: str) -> str:
        index = columns.get(field_name)
        if index is None or index >= len(row.cells):
            return ""
        return row.cells[index]

    line.serial = row.cells[0].strip() if row.cells else ""
    line.description = cell("description").strip()
    line.hsn = cell("hsn").strip()
    line.qty = parse_amount(cell("qty"))
    line.rate = parse_amount(cell("rate"))
    line.taxable = parse_amount(cell("taxable"))
    line.gst_rate = parse_amount(cell("gst").replace("%", ""))

    if line.taxable is None:
        # Fall back to the last number on the row, which is where a taxable
        # amount sits on almost every layout that lacks a proper header.
        numbers = _numbers(row)
        if numbers:
            line.taxable = numbers[-1][1]

    if line.gst_rate is not None and float(line.gst_rate) not in _VALID_GST_RATES:
        # A percentage that is not a GST rate is a discount, an HSN fragment,
        # or the next column over. Drop it rather than compare against it.
        line.gst_rate = None

    if not line.description:
        # No description column matched: take the longest non-numeric cell.
        candidates = [c for c in row.cells[1:] if not is_numeric_cell(c)]
        if candidates:
            line.description = max(candidates, key=len).strip()

    if line.taxable is None and line.qty is not None and line.rate is not None:
        line.taxable = line.qty * line.rate

    if line.taxable is None and not line.description:
        return None
    return line


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def to_iso_date(text: str) -> str:
    """Best-effort ISO date from the shapes an Indian invoice prints.

    "18 October 2026", "18-Oct-26", "18/10/2026", "2026-10-18", "Oct 18 2026"
    and the Devanagari month names all appear on real bills. Returns "" when
    the date cannot be read -- an empty cell is honest, a guessed date is not.

    Two-digit years: anything 70 and above is 1900s, everything else 2000s.
    Nothing an invoice carries will be dated 2070, and nothing from 1999 is
    still being filed.
    """
    if not text:
        return ""
    text = normalise_digits(str(text)).strip()

    # Already ISO.
    iso = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", text)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
        return ""

    # Day first: 18/10/2026, 18-10-26, 18 Oct 2026, 18-Oct-2026.
    day_first = re.match(
        r"^(\d{1,2})[\s./-]*(?:([A-Za-z]+)|(\d{1,2}))[\s./,-]*(\d{2,4})?$", text)
    if day_first:
        day_s, month_word, month_s, year_s = day_first.groups()
        # "18 Oct" with the year missing cannot be dated without guessing.
        if year_s is None:
            year_s = ""
        month = _month_number(month_word) if month_word else (
            int(month_s) if month_s else 0)
        if month:
            year = _year(year_s) if year_s else 0
            if year:
                return _iso(year, month, int(day_s))

    # Month first: "Oct 18, 2026".
    month_first = re.match(r"^([A-Za-z]+)\s+(\d{1,2})[\s,]+(\d{4})$", text)
    if month_first:
        month_word, day_s, year_s = month_first.groups()
        month = _month_number(month_word)
        if month:
            return _iso(_year(year_s), month, int(day_s))
    return ""


def _month_number(word: str) -> int:
    if not word:
        return 0
    key = word.strip().lower()[:3]
    if key in _MONTHS:
        return _MONTHS[key]
    # Devanagari and Gujarati month names as printed on bills.
    hindi = {
        "जनवरी": 1, "फ़रवरी": 2, "फरवरी": 2, "मार्च": 3, "अप्रैल": 4,
        "मई": 5, "जून": 6, "जुलाई": 7, "अगस्त": 8, "सितंबर": 9,
        "अक्टूबर": 10, "अक्तूबर": 10, "नवंबर": 11, "दिसंबर": 12,
    }
    return hindi.get(word.strip(), 0)


def _year(text: str) -> int:
    """Two-digit years, resolved. 70-99 -> 1900s, 00-69 -> 2000s."""
    year = int(text)
    if year < 100:
        year += 1900 if year >= 70 else 2000
    return year


def _iso(year: int, month: int, day: int) -> str:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_rows(rows: List[Row], source: str = "") -> Invoice:
    """Read an invoice from positional rows."""
    invoice = Invoice(source=source)
    header_index = -1

    # -- header fields ------------------------------------------------------
    for index, row in enumerate(rows):
        lowered = _label_of(row)
        joined = " ".join(row.cells)

        if not invoice.supplier_gstin:
            match = re.search(r"(?:supplier|seller|gstin)\s*[:.]?\s*"
                              + GSTIN_PATTERN.pattern, joined, re.IGNORECASE)
            if match:
                invoice.supplier_gstin = _find_gstin(match.group(0))
        found_here = _find_gstin(joined)
        if not invoice.buyer_gstin and re.search(BUYER_WORDS, lowered):
            invoice.buyer_gstin = found_here
        if (found_here and not invoice.buyer_gstin
                and found_here != invoice.supplier_gstin
                and (header_index < 0 or index < header_index)
                and _BEFORE_ITEMS.search(joined)):
            # Many bills print the buyer's GSTIN on its own line, with no
            # "Buyer" next to it. The second GSTIN above the items table is the
            # buyer's, and leaving it unread loses the check-digit test and the
            # intra/inter-state test on those bills.
            invoice.buyer_gstin = found_here
        if not invoice.buyer_name and re.search(BUYER_WORDS, lowered):
            for label in ("bill to", "buyer name", "buyer", "recipient", "customer"):
                value = _value_after_label(row, label)
                if value and not GSTIN_PATTERN.fullmatch(value.strip()):
                    invoice.buyer_name = value.strip(" :-")
                    break
        if not invoice.number:
            match = re.search(r"(?:invoice\s*(?:no|number|#)\.?)\s*:?\s*([A-Za-z0-9/\-]+)",
                              joined, re.IGNORECASE)
            if match:
                invoice.number = match.group(1)
        if not invoice.date:
            # "Dated:" contains "date", and a pattern without a boundary read the
            # extra "d" as the date itself -- which is how a perfectly good
            # invoice came back dated "d".
            match = re.search(
                r"\b(?:dated|invoice\s*date|bill\s*date|date)\b\s*[:.]?\s*"
                r"([0-9A-Za-z /\-\.]+)", joined, re.IGNORECASE)
            if match:
                invoice.date = _parse_date(match.group(1).strip())
        if not invoice.place_of_supply:
            value = _value_after_label(row, "place of supply")
            if value:
                invoice.place_of_supply = value.strip()
            elif not invoice.supplier_gstin == found_here:
                # "State: Gujarat (24)" is how a lot of bills head the place of
                # supply. Only accepted when it names a state we know, so a
                # stray "State: N/A" cannot become the place of supply.
                candidate = _value_after_label(row, "state")
                if candidate and state_code_from_name(candidate):
                    invoice.place_of_supply = candidate.strip()
        if not invoice.supplier_name and index <= 3 and len(row.cells) >= 1:
            candidate = row.cells[0].strip()
            if candidate and not re.search(r"invoice|tax|bill", candidate, re.IGNORECASE) \
                    and parse_amount(candidate) is None and len(candidate) > 3:
                invoice.supplier_name = candidate

        if header_index < 0 and _is_header_row(row):
            header_index = index

    # A supplier GSTIN that was picked up as the buyer's, or never found, gets a
    # second pass: the first GSTIN on an invoice belongs to the supplier.
    if not invoice.supplier_gstin:
        for row in rows[:header_index if header_index > 0 else len(rows)]:
            found = _find_gstin(" ".join(row.cells))
            if found:
                invoice.supplier_gstin = found
                break
    if invoice.buyer_gstin and invoice.buyer_gstin == invoice.supplier_gstin:
        seen = []
        for row in rows:
            found = _find_gstin(" ".join(row.cells))
            if found and found not in seen:
                seen.append(found)
        if len(seen) > 1:
            invoice.buyer_gstin = seen[1]

    # -- line items ---------------------------------------------------------
    if header_index >= 0:
        columns = _column_map(rows[header_index])
        for row in rows[header_index + 1:]:
            if _is_totals_row(row):
                break
            if not _looks_like_line_item(row):
                continue
            line = _build_line(row, columns)
            if line is not None:
                invoice.lines.append(line)

    # -- totals -------------------------------------------------------------
    # Labels in the scripts an invoice is actually printed in. Without these a
    # Hindi bill parses to nothing and the tool blames the bill.
    fields = [
        ("taxable_value", ("taxable value", "total taxable", "taxable amount",
                           "sub total", "subtotal", "taxable", "कर योग्य मूल्य", "कुल कर योग्य",
                           "करपात्र मूल्य", "કરપાત્ર મૂલ્ય")),
        ("cgst", ("cgst", "सीजीएसटी")),
        ("sgst", ("sgst", "utgst", "एसजीएसटी")),
        ("igst", ("igst", "आईजीएसटी")),
        ("cess", ("cess", "उपकर")),
        ("round_off", ("round off", "roundoff", "round-off", "गोलाई")),
        ("total", ("invoice total", "grand total", "amount payable", "total amount",
                   "कुल योग", "कुल राशि", "कुल", "કુલ રકમ", "કુલ")),
    ]
    for row in rows:
        joined = " ".join(row.cells)
        lowered = joined.lower()
        if "amount in words" in lowered:
            invoice.words = re.split(r"amount\s*in\s*words\s*:?", joined,
                                     flags=re.IGNORECASE)[-1].strip(" :-")
        if "words" in lowered and not invoice.words:
            invoice.words = re.split(r"words\s*:?", joined, flags=re.IGNORECASE)[-1].strip(" :-")
        for name, labels in fields:
            if getattr(invoice, name) is not None:
                continue
            # "Total" is a substring of half the labels on an invoice, and in
            # Hindi it is worse: "कुल कर योग्य मूल्य" is *taxable value* and it
            # begins with the word for total. A row that names a tax component
            # is never the grand total, so it is skipped rather than matched.
            if name == "total" and any(
                    part in lowered for part in
                    ("taxable", "कर योग्य", "करपात्र", "cgst", "sgst", "igst",
                     "cess", "उपकर", "सीजीएसटी", "एसजीएसटी", "आईजीएसटी", "round")):
                continue
            for label in labels:
                value = _value_after_label(row, label)
                if value is None:
                    continue
                amount = parse_amount(value)
                if amount is None:
                    continue
                setattr(invoice, name, amount)
                break

    if invoice.total is None and invoice.taxable_value is not None \
            and invoice.claimed_tax is not None:
        # Some invoices print the parts and leave the reader to add them. That
        # is arithmetic the checker can do, but it is *not* the invoice's own
        # claim, so it is recorded as an observation and the check says so.
        pass

    if invoice.words:
        invoice.words_amount = words_to_amount(invoice.words)

    # -- what is missing ----------------------------------------------------
    for name, human in (("supplier_gstin", "supplier GSTIN"), ("number", "invoice number"),
                        ("date", "invoice date"), ("total", "invoice total"),
                        ("taxable_value", "taxable value")):
        if not getattr(invoice, name):
            invoice.missing.append(human)

    return invoice


def parse_invoice(document: Document) -> Invoice:
    return parse_rows(list(document), source=document.source)
