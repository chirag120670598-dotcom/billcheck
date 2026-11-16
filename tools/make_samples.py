"""Generate the sample invoices the tests and the demo run on.

    python tools/make_samples.py

Writes PDFs and text files into ``data/samples/``. The PDFs are built here
rather than committed so that the numbers and the layout stay honest: if a test
needs a broken invoice, the breakage is visible in this file, in one line of
data, instead of hidden inside a binary.

Every sample has a deliberate purpose. Six of the ten are *wrong* on purpose --
a checker that only ever sees correct invoices has not been tested.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from billcheck.gst import gstin_check_character  # noqa: E402
from billcheck.money import words_to_amount  # noqa: E402

OUT = os.path.join(HERE, "data", "samples")


def valid_gstin(first14: str) -> str:
    return first14 + gstin_check_character(first14)


# ---------------------------------------------------------------------------
# a small invoice description language
# ---------------------------------------------------------------------------

SUPPLIER = {
    "name": "Shreeji Trading Company",
    "address": "14, Relief Road, Ahmedabad 380001",
    "gstin": valid_gstin("24AAPFU0939F1Z"),      # Gujarat
}
BUYER = {
    "name": "Patel Textiles Pvt Ltd",
    "address": "22, LBS Marg, Mumbai 400001",
    "gstin": valid_gstin("27ABCPD1234E1Z"),      # Maharashtra
}
#: A buyer in the supplier's own state, for the intra-state samples.
LOCAL_BUYER = {
    "name": "Patel Traders",
    "address": "8, Ashram Road, Ahmedabad 380009",
    "gstin": valid_gstin("24AABCP5555F1Z"),      # Gujarat
}

#: Each line: (serial, description, hsn, qty, rate, taxable, gst_rate)
CLEAN_LINES = [
    ("1", "Cotton Fabric 40s", "5208", "120", "450.00", "54000.00", "5"),
    ("2", "Polyester Thread", "5402", "60", "180.00", "10800.00", "12"),
    ("3", "Packaging Material", "3923", "25", "96.00", "2400.00", "18"),
]


def _pdf(path: str, invoice: dict) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(path, pagesize=A4)
    width, height = A4

    def text(x, y, value, size=9, bold=False):
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(x, y, str(value))

    y = height - 50
    text(50, y, invoice.get("title", "TAX INVOICE"), 16, True)
    y -= 24
    text(50, y, invoice["supplier"]["name"], 10, True)
    y -= 13
    text(50, y, invoice["supplier"]["address"])
    y -= 13
    text(50, y, f"GSTIN: {invoice['supplier']['gstin']}")
    y -= 20

    text(50, y, f"Invoice No: {invoice['number']}")
    text(330, y, f"Invoice Date: {invoice['date']}")
    y -= 13
    text(50, y, f"Buyer: {invoice['buyer']['name']}")
    text(330, y, f"Place of Supply: {invoice['place_of_supply']}")
    y -= 13
    text(50, y, f"Buyer GSTIN: {invoice['buyer']['gstin']}")
    y -= 26

    columns = [(50, "Sr"), (78, "Description"), (300, "HSN/SAC"), (368, "Qty"),
               (410, "Rate"), (470, "Taxable"), (552, "GST%")]
    for x, label in columns:
        text(x, y, label, 9, True)
    y -= 15

    for row in invoice["lines"]:
        for (x, _label), value in zip(columns, row):
            text(x, y, value)
        y -= 14

    y -= 12
    for label, value in invoice.get("totals", []):
        text(50, y, f"{label}: {value}", 9, True)
        y -= 14

    if invoice.get("words"):
        y -= 8
        text(50, y, f"Amount in words: {invoice['words']}")

    pdf.save()


def _money(value) -> str:
    return f"{Decimal(str(value)):.2f}"


def _line_tax(line) -> Decimal:
    taxable, rate = Decimal(str(line[5])), Decimal(str(line[6]))
    return taxable * rate / 100


def _summary(lines):
    """Taxable total and tax total, derived from the lines themselves.

    Every sample's totals are computed here rather than typed in. A sample must
    not drift out of agreement with its own line items by accident; when a
    sample is meant to be wrong, the wrongness is a deliberate adjustment
    written out on the line that makes it.
    """
    taxable = sum(Decimal(str(line[5])) for line in lines)
    tax = sum(_line_tax(line) for line in lines)
    return taxable, tax


def _say(words: str, expected: Decimal) -> str:
    """Guard: the amount in words must actually read as the number we mean."""
    got = words_to_amount(words)
    if got != expected:
        raise AssertionError(f"{words!r} reads as {got}, expected {expected}")
    return words


def _pdf_alt(path: str, invoice: dict) -> None:
    """A deliberately different layout, to keep the parser honest.

    Different column positions, different labels ("Bill To", "Dated", "State"),
    "Rs." in front of every amount, two totals sharing a line, and no GST rate
    column at all. If the parser only ever sees one template it stops being a
    parser and becomes a fixture.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(path, pagesize=A4)
    width, height = A4

    def text(x, y, value, size=9, bold=False):
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(x, y, str(value))

    y = height - 60
    text(60, y, "TAX INVOICE", 15, True)
    y -= 26
    text(60, y, invoice["supplier_name"], 10, True)
    y -= 13
    text(60, y, "Plot 9, GIDC Vatva, Ahmedabad 382445")
    y -= 13
    text(60, y, f"GSTIN: {invoice['supplier_gstin']}")
    y -= 22

    text(60, y, f"Tax Invoice No: {invoice['number']}")
    text(330, y, f"Dated: {invoice['date']}")
    y -= 16
    text(60, y, f"Bill To: {invoice['buyer_name']}")
    text(330, y, f"State: {invoice['place_of_supply']}")
    y -= 13
    text(60, y, f"GSTIN: {invoice['buyer_gstin']}")
    y -= 24

    columns = [(60, "Sr"), (95, "Item"), (260, "HSN"), (320, "Qty"),
               (370, "Rate"), (450, "Amount")]
    for x, label in columns:
        text(x, y, label, 9, True)
    y -= 15
    for row in invoice["lines"]:
        for (x, _label), value in zip(columns, row):
            text(x, y, value)
        y -= 14

    y -= 14
    text(330, y, "Taxable", 9, True)
    text(430, y, f"Rs. {invoice['taxable']}")
    y -= 14
    text(330, y, "CGST", 9, True)
    text(400, y, f"Rs. {invoice['cgst']}")
    text(490, y, "SGST", 9, True)
    text(545, y, f"Rs. {invoice['sgst']}")
    y -= 14
    text(330, y, "Round Off", 9, True)
    text(430, y, f"Rs. {invoice['round_off']}")
    y -= 14
    text(330, y, "Grand Total", 10, True)
    text(430, y, f"Rs. {invoice['total']}")
    y -= 18
    text(60, y, f"Amount in words: {invoice['words']}")
    pdf.save()


def build() -> list:
    os.makedirs(OUT, exist_ok=True)
    made = []

    taxable, tax = _summary(CLEAN_LINES)          # 67200.00 and 4428.00
    total = taxable + tax                          # 71628.00
    half = tax / 2                                 # 2214.00

    # 1. A correct invoice. Inter-state (24 -> 27), so IGST and no CGST/SGST.
    clean = {
        "number": "STC/2026-27/0482",
        "date": "18 October 2026",
        "supplier": SUPPLIER,
        "buyer": BUYER,
        "place_of_supply": "Maharashtra (27)",
        "lines": CLEAN_LINES,
        "totals": [
            ("Taxable Value", _money(taxable)),
            ("IGST", _money(tax)),
            ("CGST", "0.00"),
            ("SGST", "0.00"),
            ("Round Off", "0.00"),
            ("Invoice Total", _money(total)),
        ],
        "words": _say("Seventy One Thousand Six Hundred Twenty Eight Only", total),
    }
    path = os.path.join(OUT, "clean_interstate.pdf")
    _pdf(path, clean)
    made.append(path)

    # 2. Same invoice, intra-state: CGST + SGST instead of IGST.
    intra = dict(clean)
    intra["buyer"] = LOCAL_BUYER                                 # same state
    intra["place_of_supply"] = "Gujarat (24)"
    intra["number"] = "STC/2026-27/0483"
    intra["totals"] = [
        ("Taxable Value", _money(taxable)),
        ("CGST", _money(half)),
        ("SGST", _money(tax)),
        ("IGST", "0.00"),
        ("Invoice Total", _money(total)),
    ]
    intra["totals"][2] = ("SGST", _money(tax - half))
    path = os.path.join(OUT, "clean_intrastate.pdf")
    _pdf(path, intra)
    made.append(path)

    # 3. BROKEN, and the important one. Somebody corrected the CGST figure by
    #    twelve rupees and forgot the SGST. Note that the printed total still
    #    adds up exactly from the printed taxable value and the printed tax:
    #
    #        67200.00 + 2226.00 + 2214.00 = 71640.00
    #
    #    so a tool that only reconciles the total passes this invoice. The
    #    invoice is still wrong, and only a line-item cross-check says so.
    broken_tax = dict(intra)
    broken_tax["number"] = "STC/2026-27/0490"
    broken_cgst = half + Decimal("12.00")
    broken_tax["totals"] = [
        ("Taxable Value", _money(taxable)),
        ("CGST", _money(broken_cgst)),
        ("SGST", _money(tax - half)),
        ("IGST", "0.00"),
        ("Invoice Total", _money(taxable + tax + Decimal("12.00"))),
    ]
    # The words are made to agree with the (wrong) total on purpose: this
    # sample must fail on the arithmetic alone, not on a words mismatch.
    broken_tax["words"] = _say("Seventy One Thousand Six Hundred Forty Only",
                               taxable + tax + Decimal("12.00"))
    path = os.path.join(OUT, "broken_tax_split.pdf")
    _pdf(path, broken_tax)
    made.append(path)

    # 4. BROKEN: line 1 says 55,000 where 120 x 450 is 54,000. The tax and the
    #    total that follow are consistent with the wrong figure, so only the
    #    quantity x rate check can catch this one.
    broken_line = dict(intra)
    broken_line["number"] = "STC/2026-27/0491"
    broken_line["lines"] = [
        ("1", "Cotton Fabric 40s", "5208", "120", "450.00", "55000.00", "5"),
        ("2", "Polyester Thread", "5402", "60", "180.00", "10800.00", "12"),
        ("3", "Packaging Material", "3923", "25", "96.00", "2400.00", "18"),
    ]
    bl_taxable, bl_tax = _summary(broken_line["lines"])      # 68200, 4478
    broken_line["totals"] = [
        ("Taxable Value", _money(bl_taxable)),
        ("CGST", _money(bl_tax / 2)),
        ("SGST", _money(bl_tax / 2)),
        ("IGST", "0.00"),
        ("Invoice Total", _money(bl_taxable + bl_tax)),
    ]
    broken_line["words"] = _say("Seventy Two Thousand Six Hundred Seventy Eight Only",
                                bl_taxable + bl_tax)
    path = os.path.join(OUT, "broken_line_math.pdf")
    _pdf(path, broken_line)
    made.append(path)

    # 5. BROKEN: the buyer GSTIN fails its check digit. Everything else about
    #    this invoice is correct, so a field-extraction tool sees nothing wrong.
    bad_gstin = dict(clean)
    bad_gstin["number"] = "STC/2026-27/0492"
    bad_gstin["buyer"] = dict(BUYER, gstin="27ABCPD1234E1Z5")
    path = os.path.join(OUT, "broken_gstin.pdf")
    _pdf(path, bad_gstin)
    made.append(path)

    # 6. BROKEN: the amount in words is thirty-two rupees short of the figure.
    bad_words = dict(clean)
    bad_words["number"] = "STC/2026-27/0493"
    bad_words["words"] = "Seventy One Thousand Six Hundred Sixty Only"
    path = os.path.join(OUT, "broken_words.pdf")
    _pdf(path, bad_words)
    made.append(path)

    # 7. Correct, with paise and a round-off: the ordinary case that naive
    #    totalling arithmetic gets wrong. Tax is 4428.60, the payable amount is
    #    rounded to 71628.00, and the round-off carries the difference. The
    #    sixty paise between the line-level tax and the printed tax is inside
    #    the default one-rupee tolerance, which is exactly why the tolerance
    #    exists.
    rounded = dict(intra)
    rounded["number"] = "STC/2026-27/0494"
    round_cgst = Decimal("2214.30")
    round_tax = round_cgst * 2                                # 4428.60
    rounded["totals"] = [
        ("Taxable Value", _money(taxable)),
        ("CGST", _money(round_cgst)),
        ("SGST", _money(round_cgst)),
        ("IGST", "0.00"),
        ("Round Off", "-0.60"),
        ("Invoice Total", "71628.00"),
    ]
    assert taxable + round_tax - Decimal("0.60") == Decimal("71628.00")
    path = os.path.join(OUT, "round_off.pdf")
    _pdf(path, rounded)
    made.append(path)

    # 8. Plain text with Devanagari digits and labels -- the case that breaks
    #    every regex built on [0-9]. No line-item table: a checker must say so
    #    rather than invent one.
    hindi = f"""कर बीजक  /  TAX INVOICE
Shreeji Trading Company
GSTIN: {SUPPLIER['gstin']}
Invoice No: STC/2026-27/0500
Invoice Date: 20 October 2026
Buyer: {LOCAL_BUYER['name']}
Buyer GSTIN: {LOCAL_BUYER['gstin']}
Place of Supply: Gujarat (24)
कुल कर योग्य मूल्य: २,४००.००
CGST: ६०.००   SGST: ६०.००
Invoice Total: २,५२०.००
"""
    path = os.path.join(OUT, "devanagari.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(hindi)
    made.append(path)

    # 9. A plain-text invoice with the same shape as the PDFs, for tests that
    #    must not depend on pypdf. Tax is 333.00, split into two halves of
    #    166.50 -- paise in the tax, rupees in the total.
    plain_lines = [
        ("1", "Cotton Fabric 40s", "5208", "10", "450.00", "4500.00", "5"),
        ("2", "Polyester Thread", "5402", "5", "180.00", "900.00", "12"),
    ]
    pl_taxable, pl_tax = _summary(plain_lines)                 # 5400, 333
    plain = f"""TAX INVOICE
Shreeji Trading Company
GSTIN: {SUPPLIER['gstin']}
Invoice No: STC/2026-27/0501
Invoice Date: 21 October 2026
Buyer: {LOCAL_BUYER['name']}
Buyer GSTIN: {LOCAL_BUYER['gstin']}
Place of Supply: Gujarat (24)
Sr   Description   HSN   Qty   Rate   Taxable   GST%
1   Cotton Fabric 40s   5208   10   450.00   4500.00   5
2   Polyester Thread   5402   5   180.00   900.00   12
Taxable Value: {_money(pl_taxable)}
CGST: {_money(pl_tax / 2)}   SGST: {_money(pl_tax / 2)}
Invoice Total: {_money(pl_taxable + pl_tax)}
Amount in words: {_say('Five Thousand Seven Hundred Thirty Three Only',
                       pl_taxable + pl_tax)}
"""
    path = os.path.join(OUT, "plain_intrastate.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(plain)
    made.append(path)

    # 10. No total at all -- a real failure mode for truncated or badly exported
    #     invoices, and the parser must survive it rather than crash.
    truncated = dict(intra)
    truncated["number"] = "STC/2026-27/0502"
    truncated["totals"] = [("Taxable Value", _money(taxable))]
    path = os.path.join(OUT, "no_total.pdf")
    _pdf(path, truncated)
    made.append(path)

    # 11. The same invoice in a different house style: different column
    #     positions, "Bill To", "Dated", "State:", "Rs." in front of every
    #     amount, two totals on one line, and no GST rate column. The rate is
    #     recoverable from the totals, and the checker says that it inferred it
    #     rather than claiming the invoice printed it.
    alt = {
        "number": "VE/2026-27/0042",
        "date": "05-04-2026",
        "supplier_name": "Vasant Enterprises",
        "supplier_gstin": valid_gstin("24AAACV1234B1Z"),
        "buyer_name": "Rupal Textiles",
        "buyer_gstin": valid_gstin("24AACCR5678D1Z"),
        "place_of_supply": "Gujarat (24)",
        "taxable": "123250.00",
        "cgst": "4251.25",
        "sgst": "4251.25",
        "round_off": "-0.50",
        "total": "131752.00",
        "words": _say("One Lakh Thirty One Thousand Seven Hundred Fifty Two Only",
                      Decimal("131752")),
        # (serial, description, hsn, qty, rate, amount)
        "lines": [
            ("1", "Cotton Yarn 40s", "5205", "500", "210.50", "105250.00"),
            ("2", "Reactive Dye", "3204", "20", "900.00", "18000.00"),
        ],
    }
    path = os.path.join(OUT, "layout_variant.pdf")
    _pdf_alt(path, alt)
    made.append(path)

    return made


if __name__ == "__main__":
    for path in build():
        print(os.path.relpath(path, HERE))
