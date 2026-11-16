"""Working out the GST rate when the invoice does not print one.

Most invoices carry a rate column. Some do not -- a consolidated bill prints the
items, then the taxable value, then CGST and SGST, and leaves the rate to be
worked out. On those invoices the most valuable check in this tool would
otherwise be skipped, which is a shame when the answer is recoverable.

It is recoverable because GST rates are not a continuum. There are seven of
them, and the tax on each line is that line's taxable value times one of the
seven. With n lines there are 7^n combinations, which sounds like a lot and is
not: the search is over *sums*, and sums collide. A dynamic program over
achievable paise totals keeps at most two distinct solutions per total, so
ambiguity is detected rather than guessed away.

The result is reported as an inference, never as a fact. "The rates are
probably 5% and 18%" is useful; "the rates are 5% and 18%" would be a claim the
invoice does not support.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from .money import quantise

__all__ = ["STANDARD_RATES", "Inference", "infer_line_rates"]

#: The rates the GST Council actually uses, including the fractional ones for
#: cut and polished diamonds and the nil rate. Ordered so that a tie is broken
#: towards the rate a human would expect to see first.
STANDARD_RATES: Tuple[Decimal, ...] = tuple(
    Decimal(value) for value in
    ("0", "0.25", "1.5", "3", "5", "12", "18", "28")
)

#: Above this many lines the search is abandoned rather than run for a long
#: time on an invoice whose rates nobody was going to read anyway.
MAX_LINES = 12

#: Above this many live states the search is abandoned. Real invoices stay in
#: the low hundreds; this only guards against a pathological document.
MAX_STATES = 20000


class Inference:
    """What the search found."""

    __slots__ = ("rates", "status", "detail")

    def __init__(self, rates: Optional[List[Decimal]], status: str, detail: str = ""):
        self.rates = rates
        self.status = status          # "unique", "ambiguous", "none", "skipped"
        self.detail = detail

    def __repr__(self) -> str:        # pragma: no cover - debugging aid
        return f"Inference({self.status}, {self.rates})"


def _candidates(taxables: Sequence[Decimal]) -> List[List[Tuple[Decimal, int]]]:
    out = []
    for taxable in taxables:
        per_line = []
        for rate in STANDARD_RATES:
            owed = quantise(Decimal(taxable) * rate / 100)
            per_line.append((rate, int(owed * 100)))
        out.append(per_line)
    return out


def infer_line_rates(lines: Sequence, target, *,
                     rates: Sequence[Decimal] = STANDARD_RATES,
                     tolerance=Decimal("1.00")) -> Inference:
    """Find the standard rates that reproduce ``target`` exactly.

    ``lines`` needs ``taxable`` on each entry; ``target`` is the tax the invoice
    charges (CGST + SGST + IGST, cess excluded, because cess has its own rates).
    """
    taxable_lines = [line for line in lines if line.taxable is not None]
    if not taxable_lines:
        return Inference(None, "skipped", "no line has a taxable value")
    if len(taxable_lines) > MAX_LINES:
        return Inference(None, "skipped",
                         f"{len(taxable_lines)} lines is more than this search "
                         f"will take on ({MAX_LINES})")
    if target is None:
        return Inference(None, "skipped", "the invoice charges no tax")

    taxables = [Decimal(line.taxable) for line in taxable_lines]
    per_line_candidates = [
        [(rate, int(quantise(Decimal(taxable) * rate / 100) * 100))
         for rate in rates]
        for taxable in taxables
    ]

    # states maps an achievable paise total to up to two distinct rate paths.
    states: Dict[int, List[Tuple[Decimal, ...]]] = {0: [()]}
    for options in per_line_candidates:
        nxt: Dict[int, List[Tuple[Decimal, ...]]] = {}
        for total, paths in states.items():
            for rate, tax_paise in options:
                key = total + tax_paise
                entry = nxt.setdefault(key, [])
                for path in paths:
                    candidate = path + (rate,)
                    if len(entry) < 2 and candidate not in entry:
                        entry.append(candidate)
        if len(nxt) > MAX_STATES:
            return Inference(None, "skipped", "too many combinations to search")
        states = nxt

    target_paise = int(Decimal(target) * 100)
    budget = int(Decimal(tolerance) * 100)
    hits = [(total, paths) for total, paths in states.items()
            if abs(total - target_paise) <= budget]

    if not hits:
        return Inference(None, "none",
                         "no combination of standard GST rates reproduces the "
                         "tax on this invoice")

    flat = []
    for _total, paths in hits:
        flat.extend(paths)
    distinct = []
    for path in flat:
        if path not in distinct:
            distinct.append(path)

    if len(distinct) > 1:
        return Inference(None, "ambiguous",
                         f"{len(distinct)} combinations of standard rates give the "
                         f"same tax, so the rate cannot be pinned down")

    return Inference(list(distinct[0]), "unique")
