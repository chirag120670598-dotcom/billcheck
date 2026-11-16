"""Parsing: rows in, an Invoice out.

Half of these tests use the plain-text path, which needs nothing installed, and
half use a real PDF, because the PDF path is where the layout actually bites.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from tests.sample_support import (HAVE_PYPDF, HAVE_REPORTLAB,
                                  sample_path, samples_present)

from billcheck.parse import parse_invoice, to_iso_date
from billcheck.pdf import NoTextLayer, read_any, read_pdf, rows_from_text

TEXT_INVOICE = """TAX INVOICE
Shreeji Trading Company
GSTIN: 24AAPFU0939F1Z1
Invoice No: STC/2026-27/0501
Invoice Date: 21 October 2026
Buyer: Patel Traders
Buyer GSTIN: 24AABCP5555F1ZK
Place of Supply: Gujarat (24)
Sr   Description   HSN   Qty   Rate   Taxable   GST%
1   Cotton Fabric 40s   5208   10   450.00   4500.00   5
2   Polyester Thread   5402   5   180.00   900.00   12
Taxable Value: 5400.00
CGST: 166.50   SGST: 166.50
Invoice Total: 5733.00
Amount in words: Five Thousand Seven Hundred Thirty Three Only
"""


def _write(text: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                         encoding="utf-8")
    handle.write(text)
    handle.close()
    return handle.name


class TextParsingTests(unittest.TestCase):

    def setUp(self):
        self.path = _write(TEXT_INVOICE)
        self.invoice = parse_invoice(read_any(self.path))

    def tearDown(self):
        os.unlink(self.path)

    def test_header(self):
        inv = self.invoice
        self.assertEqual(inv.number, "STC/2026-27/0501")
        self.assertEqual(inv.date_iso, "2026-10-21")
        self.assertEqual(inv.supplier_gstin, "24AAPFU0939F1Z1")
        self.assertEqual(inv.buyer_gstin, "24AABCP5555F1ZK")
        self.assertEqual(inv.place_of_supply, "Gujarat (24)")

    def test_buyer_name_is_not_swallowed_by_the_next_field(self):
        self.assertEqual(self.invoice.buyer_name, "Patel Traders")

    def test_two_line_items(self):
        lines = self.invoice.lines
        self.assertEqual(len(lines), 2)
        first = lines[0]
        self.assertEqual(first.serial, "1")
        self.assertEqual(first.description, "Cotton Fabric 40s")
        self.assertEqual(first.hsn, "5208")
        self.assertEqual(str(first.qty), "10")
        self.assertEqual(str(first.rate), "450.00")
        self.assertEqual(str(first.taxable), "4500.00")
        self.assertEqual(str(first.gst_rate), "5")

    def test_totals(self):
        inv = self.invoice
        self.assertEqual(str(inv.taxable_value), "5400.00")
        self.assertEqual(str(inv.cgst), "166.50")
        self.assertEqual(str(inv.sgst), "166.50")
        self.assertEqual(str(inv.total), "5733.00")

    def test_words(self):
        self.assertEqual(str(self.invoice.words_amount), "5733")

    def test_missing_fields_are_recorded_not_hidden(self):
        sparse = parse_invoice(read_any(_write("TAX INVOICE\nnothing here\n")))
        self.assertIn("invoice total", sparse.missing)
        self.assertIsNone(sparse.total)


class DateTests(unittest.TestCase):

    def test_shapes(self):
        cases = {
            "18 October 2026": "2026-10-18",
            "18-Oct-2026": "2026-10-18",
            "18/10/2026": "2026-10-18",
            "18-10-2026": "2026-10-18",
            "2026-10-18": "2026-10-18",
            "Oct 18, 2026": "2026-10-18",
            "18/10/26": "2026-10-18",
            "१८/१०/२०२६": "2026-10-18",
        }
        for text, expected in cases.items():
            self.assertEqual(to_iso_date(text), expected, text)

    def test_unreadable_dates_return_empty_rather_than_a_guess(self):
        for text in ("", "18 Oct", "sometime", "32/13/2026"):
            self.assertEqual(to_iso_date(text), "", text)


class RowModelTests(unittest.TestCase):

    def test_rows_from_text_keeps_columns(self):
        rows = rows_from_text("Sr Description HSN Qty Rate\n1 Fabric 5208 10 450.00")
        self.assertEqual(len(rows), 2)
        self.assertIn("Fabric", " ".join(rows[1].cells))

    def test_no_text_layer_is_its_own_error(self):
        """A scanned PDF must say so, not parse to an empty invoice."""
        self.assertTrue(issubclass(NoTextLayer, Exception))


@unittest.skipUnless(HAVE_PYPDF and HAVE_REPORTLAB,
                     "needs pypdf and reportlab to build a text-free PDF")
class ScannedPdfTests(unittest.TestCase):

    def setUp(self):
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        handle, self.path = tempfile.mkstemp(suffix=".pdf")
        os.close(handle)
        page = canvas.Canvas(self.path, pagesize=A4)
        page.rect(50, 50, 500, 700, stroke=1, fill=0)   # a shape, no text
        page.save()

    def tearDown(self):
        os.unlink(self.path)

    def test_a_scan_is_refused_clearly(self):
        with self.assertRaises(NoTextLayer) as caught:
            read_any(self.path)
        message = str(caught.exception)
        self.assertIn("no text layer", message)
        self.assertIn("scan", message)


@unittest.skipUnless(HAVE_PYPDF and samples_present("clean_interstate.pdf"),
                     "needs pypdf and the generated samples")
class PdfParsingTests(unittest.TestCase):

    def test_columns_are_reconstructed_not_glued(self):
        doc = read_pdf(sample_path("clean_interstate.pdf"))
        line = [row for row in doc.rows
                if row.cells[:2] == ["1", "Cotton Fabric 40s"]]     # noqa: E501
        self.assertEqual(len(line), 1, [r.cells for r in doc.rows])
        self.assertEqual(line[0].cells,
                         ["1", "Cotton Fabric 40s", "5208", "120",
                          "450.00", "54000.00", "5"])

    def test_three_line_items_survive(self):
        invoice = parse_invoice(read_any(sample_path("clean_interstate.pdf")))
        self.assertEqual(len(invoice.lines), 3)
        self.assertEqual([line.description for line in invoice.lines],
                         ["Cotton Fabric 40s", "Polyester Thread",
                          "Packaging Material"])

    def test_header_fields(self):
        invoice = parse_invoice(read_any(sample_path("clean_interstate.pdf")))
        self.assertEqual(invoice.number, "STC/2026-27/0482")
        self.assertEqual(invoice.buyer_name, "Patel Textiles Pvt Ltd")
        self.assertEqual(invoice.place_of_supply, "Maharashtra (27)")
        self.assertEqual(invoice.supplier_gstin, "24AAPFU0939F1Z1")

    def test_stray_trailing_text_does_not_break_the_total(self):
        """Rows after the last total are ignored, not folded into it."""
        invoice = parse_invoice(read_any(sample_path("clean_interstate.pdf")))
        self.assertEqual(str(invoice.total), "71628.00")


if __name__ == "__main__":
    unittest.main()
