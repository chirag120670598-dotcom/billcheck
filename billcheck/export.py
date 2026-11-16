"""Output shapes: JSON for machines, CSV for Tally and Excel, Markdown for people.

A verification report that nobody can act on is not worth much. Three consumers
matter, and they want three different things:

* an accountant, who wants one row per invoice to paste into a register and a
  short list of what to look at;
* a bookkeeping workflow, which wants the line items, not the findings;
* a developer or a test, which wants everything as structured data.

The CSV is a *sales register*, not a Tally XML export. Tally's XML import is a
large, version-sensitive format and pretending to emit it would be a claim this
tool cannot back. A register-shaped CSV opens in Tally, in Excel and in Google
Sheets, and that is what is offered.
"""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from typing import Iterable, List, Sequence

from .money import format_inr
from .verify import Report

__all__ = [
    "REGISTER_COLUMNS",
    "LINE_COLUMNS",
    "register_row",
    "line_rows",
    "to_json",
    "write_json",
    "write_register",
    "write_lines",
    "review_sheet",
]


REGISTER_COLUMNS = [
    "source",
    "verdict",
    "voucher_date",
    "voucher_type",
    "voucher_number",
    "party_name",
    "party_gstin",
    "place_of_supply",
    "taxable_value",
    "cgst",
    "sgst",
    "igst",
    "cess",
    "round_off",
    "invoice_total",
    "failures",
    "warnings",
]

LINE_COLUMNS = [
    "source",
    "voucher_number",
    "serial",
    "description",
    "hsn_sac",
    "quantity",
    "rate",
    "taxable_value",
    "gst_rate",
]


def _plain(value) -> str:
    """A number as a plain decimal string, or empty. No thousands separators:
    a CSV full of commas inside numbers is a CSV nobody can parse."""
    if value is None:
        return ""
    return f"{Decimal(value):.2f}"


def register_row(report: Report) -> dict:
    invoice = report.invoice
    return {
        "source": invoice.source or "",
        "verdict": report.verdict,
        "voucher_date": invoice.date_iso or "",
        "voucher_type": "Sales",
        "voucher_number": invoice.number or "",
        "party_name": invoice.buyer_name or "",
        "party_gstin": invoice.buyer_gstin or "",
        "place_of_supply": invoice.place_of_supply or "",
        "taxable_value": _plain(invoice.taxable_value),
        "cgst": _plain(invoice.cgst),
        "sgst": _plain(invoice.sgst),
        "igst": _plain(invoice.igst),
        "cess": _plain(invoice.cess),
        "round_off": _plain(invoice.round_off),
        "invoice_total": _plain(invoice.total),
        "failures": "; ".join(c.title for c in report.failures),
        "warnings": "; ".join(c.title for c in report.warnings),
    }


def line_rows(report: Report) -> List[dict]:
    invoice = report.invoice
    out = []
    for line in invoice.lines:
        out.append({
            "source": invoice.source or "",
            "voucher_number": invoice.number or "",
            "serial": line.serial or "",
            "description": line.description or "",
            "hsn_sac": line.hsn or "",
            "quantity": _plain(line.qty),
            "rate": _plain(line.rate),
            "taxable_value": _plain(line.taxable),
            "gst_rate": _plain(line.gst_rate),
        })
    return out


def _csv(rows: Sequence[dict], columns: Sequence[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def to_json(reports: Iterable[Report]) -> str:
    payload = {
        "tool": "billcheck",
        "schema": 1,
        "invoices": [report.to_dict() for report in reports],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def write_json(reports: Sequence[Report], path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(to_json(reports))


def write_register(reports: Sequence[Report], path: str) -> None:
    rows = [register_row(report) for report in reports]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(_csv(rows, REGISTER_COLUMNS))


def write_lines(reports: Sequence[Report], path: str) -> None:
    rows = []
    for report in reports:
        rows.extend(line_rows(report))
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(_csv(rows, LINE_COLUMNS))


_VERDICT_NOTE = {
    "CLEAN": "nothing found",
    "REVIEW": "look at the warnings",
    "SUSPECT": "a field cannot be trusted",
    "BROKEN": "the arithmetic is wrong",
}


def review_sheet(reports: Sequence[Report]) -> str:
    """A short document to work from: what to look at, in priority order."""
    lines: List[str] = []
    total = len(reports)
    counts = {}
    for report in reports:
        counts[report.verdict] = counts.get(report.verdict, 0) + 1

    lines.append("# Invoice review sheet")
    lines.append("")
    summary = ", ".join(f"{counts.get(k, 0)} {k}" for k in
                        ("BROKEN", "SUSPECT", "REVIEW", "CLEAN"))
    lines.append(f"{total} invoice(s) checked: {summary}.")
    lines.append("")

    problem = [r for r in reports if r.failures]
    if problem:
        lines.append("## Needs attention")
        lines.append("")
        for report in problem:
            invoice = report.invoice
            name = invoice.source or invoice.number or "invoice"
            lines.append(f"### {name} — {report.verdict}")
            lines.append("")
            lines.append(f"*{report.verdict}: {_VERDICT_NOTE.get(report.verdict, '')}*")
            lines.append("")
            if invoice.number or invoice.total is not None:
                bits = []
                if invoice.number:
                    bits.append(f"invoice {invoice.number}")
                if invoice.date:
                    bits.append(f"dated {invoice.date}")
                if invoice.buyer_name:
                    bits.append(f"to {invoice.buyer_name}")
                if invoice.total is not None:
                    bits.append(f"for {format_inr(invoice.total)}")
                lines.append("Read as: " + ", ".join(bits) + ".")
                lines.append("")
            for check in report.sorted_checks():
                if check.status == "fail":
                    lines.append(f"- **{check.title}** — {check.detail}")
            for check in report.sorted_checks():
                if check.status == "warn":
                    lines.append(f"- *{check.title}* — {check.detail}")
            lines.append("")

    clean = [r for r in reports if not r.failures and not r.warnings]
    if clean:
        lines.append("## Nothing found")
        lines.append("")
        for report in clean:
            invoice = report.invoice
            name = invoice.source or invoice.number or "invoice"
            amount = format_inr(invoice.total) if invoice.total is not None else "-"
            lines.append(f"- {name} — {invoice.number or 'no number'} — {amount}")
        lines.append("")

    skipped_notes = set()
    for report in reports:
        for check in report.checks:
            if check.status == "skip" and check.detail:
                skipped_notes.add(check.title)
    if skipped_notes:
        lines.append("## Not checked")
        lines.append("")
        for note in sorted(skipped_notes):
            lines.append(f"- {note}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "Checks are arithmetic and format only. billcheck cannot tell you whether "
        "a supply was actually made, whether the rate is the right rate for the "
        "goods, or whether the invoice was issued in time. It tells you whether "
        "the numbers on the page agree with each other."
    )
    lines.append("")
    return "\n".join(lines)
