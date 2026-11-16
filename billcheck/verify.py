"""The checks. This is the product.

Any OCR service can hand you fields. The question a CA actually has is: *is
this invoice internally consistent?* That is arithmetic, not machine learning,
and arithmetic is something software can get exactly right.

Ten checks, in the order a person would do them:

  1. supplier GSTIN is a real, correctly-checked GSTIN
  2. buyer GSTIN is too (skipped when the invoice has none)
  3. every line's taxable equals quantity x rate
  4. the lines add up to the stated taxable value
  5. the tax charged equals the tax the line rates imply
  6. CGST and SGST are equal, and IGST is used only for inter-state supply
  7. the place of supply agrees with the tax split
  8. taxable + tax + round-off equals the printed total
  9. the amount in words matches the amount in figures
 10. the invoice number and date are present and sane

Two ideas do most of the work.

**Line-level cross-checking.** Checking only the total is not enough, and this
is not a theoretical worry. An invoice can print a taxable value, a tax and a
total that add up perfectly, while the tax it prints is not the tax its own line
items imply -- the total is self-consistent and the invoice is still wrong. The
sample ``broken_tax_split.pdf`` in this repository is exactly that invoice, and
a total-only checker passes it.

**Tolerances that are stated.** Comparisons allow one rupee at the aggregate
level, because rounding per line and rounding at the end genuinely differ. The
tolerance is a parameter, printed in the report, not a hidden fudge factor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional

from .gst import state_name, validate_gstin
from .infer import infer_line_rates
from .money import format_inr, quantise
from .parse import Invoice

__all__ = ["Check", "Report", "verify", "PASS", "FAIL", "WARN", "SKIP"]

PASS = "pass"
FAIL = "fail"
WARN = "warn"
SKIP = "skip"

#: What a failure means. ``money`` findings mean the arithmetic is wrong and
#: somebody loses money; ``identity`` findings mean a field cannot be trusted;
#: ``suspicious`` findings are worth a look but do not prove anything.
MONEY = "money"
IDENTITY = "identity"
SUSPICIOUS = "suspicious"

_SEVERITY_ORDER = {FAIL: 0, WARN: 1, SKIP: 2, PASS: 3}


@dataclass
class Check:
    key: str
    title: str
    status: str
    detail: str = ""
    expected: Optional[str] = None
    actual: Optional[str] = None
    kind: str = MONEY

    @property
    def ok(self) -> bool:
        return self.status == PASS

    def __str__(self) -> str:
        mark = {PASS: "PASS", FAIL: "FAIL", WARN: "WARN", SKIP: "SKIP"}[self.status]
        return f"[{mark}] {self.title}: {self.detail}"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "kind": self.kind,
            "detail": self.detail,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class Report:
    invoice: Invoice
    checks: List[Check] = field(default_factory=list)
    tolerance: Decimal = Decimal("1.00")

    @property
    def failures(self) -> List[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def warnings(self) -> List[Check]:
        return [c for c in self.checks if c.status == WARN]

    @property
    def money_failures(self) -> List[Check]:
        return [c for c in self.failures if c.kind == MONEY]

    @property
    def passed(self) -> bool:
        """An invoice passes only when nothing failed. Warnings are not failures."""
        return not self.failures

    @property
    def verdict(self) -> str:
        if self.money_failures:
            return "BROKEN"
        if self.failures:
            return "SUSPECT"
        if self.warnings:
            return "REVIEW"
        return "CLEAN"

    def sorted_checks(self) -> List[Check]:
        return sorted(self.checks, key=lambda c: (_SEVERITY_ORDER.get(c.status, 9),
                                                  c.key))

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "passed": self.passed,
            "tolerance": str(self.tolerance),
            "summary": {
                "checks": len(self.checks),
                "failed": len(self.failures),
                "warned": len(self.warnings),
                "skipped": len([c for c in self.checks if c.status == SKIP]),
            },
            "checks": [c.to_dict() for c in self.checks],
            "invoice": self.invoice.to_dict(),
        }


def _money(value) -> str:
    return format_inr(value) if value is not None else "-"


def _close(a, b, tolerance: Decimal) -> bool:
    return abs(Decimal(a) - Decimal(b)) <= tolerance


# ---------------------------------------------------------------------------
# individual checks
# ---------------------------------------------------------------------------

def _check_gstin(invoice: Invoice, tolerance: Decimal, *, buyer: bool) -> Check:
    value = invoice.buyer_gstin if buyer else invoice.supplier_gstin
    label = "buyer" if buyer else "supplier"
    key = f"{label}_gstin"
    title = f"{label.capitalize()} GSTIN is valid"

    if not value:
        # An empty read is not an invalid GSTIN.
        status = SKIP if (buyer or invoice.is_empty) else FAIL
        return Check(key, title, status,
                     f"no {label} GSTIN found on the invoice"
                     + (" (common on a B2C bill)" if buyer else ""),
                     kind=IDENTITY)

    ok, reason = validate_gstin(value)
    if ok:
        return Check(key, title, PASS, f"{value} — {reason}",
                     expected="a GSTIN whose check character matches",
                     actual=value, kind=IDENTITY)
    return Check(key, title, FAIL, f"{value} — {reason}",
                 expected="a GSTIN whose check character matches",
                 actual=value, kind=IDENTITY)


def _check_line_math(invoice: Invoice, tolerance: Decimal) -> Check:
    key, title = "line_math", "Each line's taxable equals quantity x rate"
    lines = [line for line in invoice.lines
             if line.qty is not None and line.rate is not None and line.taxable is not None]
    if not lines:
        return Check(key, title, SKIP, "no line had both a quantity and a rate",
                     kind=MONEY)

    problems = []
    for line in lines:
        expected = quantise(Decimal(line.qty) * Decimal(line.rate))
        if not _close(expected, line.taxable, tolerance):
            problems.append(
                f"line {line.serial or '?'}: {line.qty} x {line.rate} = "
                f"{_money(expected)} but taxable is {_money(line.taxable)}")

    if problems:
        return Check(key, title, FAIL, "; ".join(problems), kind=MONEY)
    return Check(key, title, PASS, f"{len(lines)} line(s) reconcile", kind=MONEY)


def _check_line_sum(invoice: Invoice, tolerance: Decimal) -> Check:
    key, title = "lines_sum_taxable", "Line items add up to the taxable value"
    items = [line for line in invoice.lines if line.taxable is not None]
    if not items:
        return Check(key, title, SKIP, "no line items were read", kind=MONEY)
    if invoice.taxable_value is None:
        return Check(key, title, SKIP, "the invoice states no taxable value", kind=MONEY)

    total = sum(Decimal(line.taxable) for line in items)
    if _close(total, invoice.taxable_value, tolerance):
        return Check(key, title, PASS,
                     f"{len(items)} line(s) total {_money(total)}, "
                     f"invoice says {_money(invoice.taxable_value)}", kind=MONEY)
    return Check(key, title, FAIL,
                 f"lines total {_money(total)}, invoice states "
                 f"{_money(invoice.taxable_value)} — difference "
                 f"{_money(Decimal(total) - Decimal(invoice.taxable_value))}",
                 expected=_money(total), actual=_money(invoice.taxable_value),
                 kind=MONEY)


def _line_tax_implied(invoice: Invoice):
    """Tax the line items imply, or None if any line lacks a usable rate.

    None when there are no lines at all. An invoice with no line items is a
    parsing outcome, not a finding about the invoice, and must not be reported
    as though the tax were wrong.
    """
    if not invoice.lines:
        return None
    total = Decimal(0)
    for line in invoice.lines:
        if line.taxable is None or line.gst_rate is None:
            return None
        total += Decimal(line.taxable) * Decimal(line.gst_rate) / 100
    return total


def _rates_from_inference(invoice: Invoice, tolerance: Decimal):
    """Try to recover the missing rates. Returns a Check, or None to carry on."""
    target = invoice.tax_excluding_cess
    result = infer_line_rates(invoice.lines, target, tolerance=tolerance)

    if result.status == "unique":
        printed = ", ".join(f"{rate.normalize():f}%" for rate in result.rates)
        return Check(
            "tax_matches_lines",
            "Tax charged equals the tax the line rates imply",
            WARN,
            f"no rate column on this invoice; the rates that fit are {printed}, "
            f"and they reproduce the {_money(target)} of tax exactly. That is an "
            f"inference from the totals, not something the invoice states",
            expected=_money(target), actual=_money(target), kind=MONEY)

    if result.status == "none":
        return Check(
            "tax_matches_lines",
            "Tax charged equals the tax the line rates imply",
            WARN,
            f"no rate column on this invoice, and no combination of standard GST "
            f"rates reproduces the {_money(target)} of tax charged. Worth a look "
            f"by hand — a non-standard rate or a cess would also explain it",
            actual=_money(target), kind=MONEY)

    if result.status == "ambiguous":
        return Check(
            "tax_matches_lines",
            "Tax charged equals the tax the line rates imply",
            WARN,
            f"no rate column on this invoice, and {result.detail}",
            actual=_money(target), kind=MONEY)

    return None


def _check_tax_matches_lines(invoice: Invoice, tolerance: Decimal) -> Check:
    key, title = "tax_matches_lines", "Tax charged equals the tax the line rates imply"
    claimed = invoice.claimed_tax
    implied = _line_tax_implied(invoice)

    if implied is None:
        if invoice.lines and claimed is not None:
            inferred = _rates_from_inference(invoice, tolerance)
            if inferred is not None:
                return inferred
        return Check(key, title, SKIP,
                     "at least one line had no GST rate, so the tax cannot be "
                     "recomputed", kind=MONEY)
    if claimed is None:
        return Check(key, title, SKIP, "the invoice states no tax", kind=MONEY)

    if _close(implied, claimed, tolerance):
        return Check(key, title, PASS,
                     f"lines imply {_money(implied)}, invoice charges "
                     f"{_money(claimed)}", kind=MONEY)

    return Check(key, title, FAIL,
                 f"lines imply {_money(implied)} but the invoice charges "
                 f"{_money(claimed)} — over by {_money(Decimal(claimed) - Decimal(implied))}",
                 expected=_money(implied), actual=_money(claimed), kind=MONEY)


def _is_interstate(invoice: Invoice) -> Optional[bool]:
    """Is this supply across a state border? From the GSTINs where possible."""
    supplier = invoice.supplier_state
    supply = invoice.supply_state
    if supplier and supply:
        return supplier != supply
    if supplier and invoice.buyer_gstin:
        buyer = invoice.buyer_gstin[:2]
        if buyer in ("00",):
            return None
        return supplier != buyer
    if invoice.igst is not None and invoice.igst > 0:
        return True
    if (invoice.cgst or 0) > 0 or (invoice.sgst or 0) > 0:
        return False
    return None


def _check_split(invoice: Invoice, tolerance: Decimal) -> Check:
    key, title = "tax_split", "CGST and SGST are equal, and IGST is not mixed in"
    cgst = invoice.cgst or Decimal(0)
    sgst = invoice.sgst or Decimal(0)
    igst = invoice.igst or Decimal(0)

    if invoice.cgst is None and invoice.sgst is None and invoice.igst is None:
        return Check(key, title, SKIP, "the invoice shows no tax breakdown", kind=MONEY)

    problems = []
    if not _close(cgst, sgst, tolerance):
        problems.append(f"CGST {_money(cgst)} is not equal to SGST {_money(sgst)}")
    if igst > 0 and (cgst > 0 or sgst > 0):
        problems.append("both IGST and CGST/SGST are charged on one invoice")

    if problems:
        return Check(key, title, FAIL, "; ".join(problems), kind=MONEY)
    return Check(key, title, PASS,
                 f"CGST {_money(cgst)} = SGST {_money(sgst)}, IGST {_money(igst)}",
                 kind=MONEY)


def _check_place_of_supply(invoice: Invoice, tolerance: Decimal) -> Check:
    key, title = "place_of_supply", "The place of supply agrees with the tax split"
    interstate = _is_interstate(invoice)
    if interstate is None:
        return Check(key, title, SKIP, "not enough information to tell intra from inter-state",
                     kind=MONEY)

    igst = invoice.igst or Decimal(0)
    cgst = invoice.cgst or Decimal(0)
    sgst = invoice.sgst or Decimal(0)

    if interstate and not (igst > 0) and (cgst > 0 or sgst > 0):
        return Check(key, title, FAIL,
                     f"supplier is in {state_name(invoice.supplier_state or '')} and the "
                     f"place of supply is {invoice.place_of_supply or 'elsewhere'}, so this "
                     f"is an inter-state supply and IGST should be charged — but the "
                     f"invoice charges CGST/SGST", kind=MONEY)
    if interstate is False and igst > 0:
        return Check(key, title, FAIL,
                     "supplier and place of supply are in the same state, so CGST/SGST "
                     "should be charged — but the invoice charges IGST", kind=MONEY)

    kind = "inter-state (IGST)" if interstate else "intra-state (CGST+SGST)"
    return Check(key, title, PASS, f"consistent: {kind}", kind=MONEY)


def _check_total(invoice: Invoice, tolerance: Decimal) -> Check:
    key, title = "total_reconciles", "Taxable value plus tax plus round-off equals the total"
    if invoice.total is None:
        return Check(key, title, WARN,
                     "no total was found — either the invoice does not print one "
                     "or this parser could not locate it", kind=SUSPICIOUS)
    if invoice.taxable_value is None:
        return Check(key, title, SKIP, "no taxable value to add up", kind=MONEY)

    tax = invoice.claimed_tax or Decimal(0)
    round_off = invoice.round_off or Decimal(0)
    computed = Decimal(invoice.taxable_value) + Decimal(tax) + Decimal(round_off)

    if _close(computed, invoice.total, Decimal("0.01")):
        return Check(key, title, PASS,
                     f"{_money(invoice.taxable_value)} + {_money(tax)}"
                     + (f" {_money(round_off)}" if round_off else "")
                     + f" = {_money(invoice.total)}", kind=MONEY)

    return Check(key, title, FAIL,
                 f"computed {_money(computed)} but the invoice prints "
                 f"{_money(invoice.total)} — difference "
                 f"{_money(Decimal(computed) - Decimal(invoice.total))}",
                 expected=_money(computed), actual=_money(invoice.total), kind=MONEY)


def _check_words(invoice: Invoice, tolerance: Decimal) -> Check:
    key, title = "amount_in_words", "The amount in words matches the amount in figures"
    if not invoice.words:
        return Check(key, title, SKIP, "the invoice states no amount in words",
                     kind=SUSPICIOUS)
    if invoice.words_amount is None:
        return Check(key, title, SKIP, f"could not read the words: {invoice.words!r}",
                     kind=SUSPICIOUS)
    if invoice.total is None:
        return Check(key, title, SKIP, "no figure total to compare against",
                     kind=SUSPICIOUS)

    if _close(invoice.words_amount, invoice.total, tolerance):
        return Check(key, title, PASS,
                     f"words read as {_money(invoice.words_amount)}", kind=SUSPICIOUS)
    return Check(key, title, FAIL,
                 f"words say {_money(invoice.words_amount)} but the figures say "
                 f"{_money(invoice.total)}", expected=_money(invoice.words_amount),
                 actual=_money(invoice.total), kind=SUSPICIOUS)


def _check_identity_fields(invoice: Invoice, tolerance: Decimal) -> Check:
    key, title = "identity_fields", "Invoice number and date are present"
    problems = []
    if not invoice.number:
        problems.append("no invoice number")
    if not invoice.date:
        problems.append("no invoice date")
    elif not invoice.date_iso:
        problems.append(f"date {invoice.date!r} is not in a recognisable format")

    if problems:
        return Check(key, title, WARN, "; ".join(problems), kind=SUSPICIOUS)
    return Check(key, title, PASS,
                 f"{invoice.number} dated {invoice.date_iso or invoice.date}",
                 kind=SUSPICIOUS)


def _check_line_items(invoice: Invoice, tolerance: Decimal) -> Check:
    key, title = "line_items", "Line items were found"
    if invoice.lines:
        return Check(key, title, PASS, f"{len(invoice.lines)} line item(s) read",
                     kind=SUSPICIOUS)
    if invoice.is_empty:
        return Check(key, title,
                     WARN if not invoice.lines else SKIP,
                     "nothing that looks like an invoice was found in this file — "
                     "no number, no GSTIN, no totals and no line items were read",
                     kind=SUSPICIOUS)
    return Check(key, title, WARN,
                 "no line item table was found, so nothing was cross-checked "
                 "below the totals — the arithmetic checks that matter most "
                 "could not run", kind=SUSPICIOUS)


def _check_hsn(invoice: Invoice, tolerance: Decimal) -> Check:
    key, title = "hsn_codes", "Line items carry a usable HSN or SAC code"
    if not invoice.lines:
        return Check(key, title, SKIP, "no line items were read", kind=SUSPICIOUS)

    missing = [line.serial or "?" for line in invoice.lines if not line.hsn]
    odd = [f"{line.serial}:{line.hsn}" for line in invoice.lines
           if line.hsn and not line.hsn.replace(" ", "").isdigit()]

    if missing:
        return Check(key, title, WARN,
                     f"no HSN on line(s) {', '.join(missing)}", kind=SUSPICIOUS)
    if odd:
        return Check(key, title, WARN,
                     f"HSN is not a plain digit code: {', '.join(odd)}", kind=SUSPICIOUS)
    return Check(key, title, PASS, f"{len(invoice.lines)} line(s) carry an HSN",
                 kind=SUSPICIOUS)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def verify(invoice: Invoice, *, tolerance=Decimal("1.00")) -> Report:
    """Run every check and return a report.

    ``tolerance`` covers the difference between rounding tax per line and
    rounding it once at the end. One rupee by default. Tighten it to a paisa if
    you would rather see every rounding difference than miss one.
    """
    tolerance = Decimal(str(tolerance))
    report = Report(invoice=invoice, tolerance=tolerance)

    if invoice.is_empty:
        # One honest sentence beats twelve findings about fields that are not
        # there because the file is not an invoice.
        report.checks = [Check(
            "line_items", "This file contains an invoice", WARN,
            "nothing that looks like an invoice was found in this file — no "
            "number, no GSTIN, no totals and no line items were read. If it is "
            "a scan or a photograph, billcheck cannot read it: it needs a PDF "
            "with a text layer", kind=SUSPICIOUS)]
        return report

    report.checks = [
        _check_gstin(invoice, tolerance, buyer=False),
        _check_gstin(invoice, tolerance, buyer=True),
        _check_line_math(invoice, tolerance),
        _check_line_sum(invoice, tolerance),
        _check_tax_matches_lines(invoice, tolerance),
        _check_split(invoice, tolerance),
        _check_place_of_supply(invoice, tolerance),
        _check_total(invoice, tolerance),
        _check_words(invoice, tolerance),
        _check_line_items(invoice, tolerance),
        _check_hsn(invoice, tolerance),
        _check_identity_fields(invoice, tolerance),
    ]
    return report
