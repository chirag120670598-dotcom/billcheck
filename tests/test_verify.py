"""The checks themselves, on hand-built invoices.

No PDFs here: these tests are about arithmetic, so the invoice is constructed
directly and the layout never enters the picture.
"""

from __future__ import annotations

import copy
import unittest
from decimal import Decimal

from billcheck.parse import Invoice, ParsedLine
from billcheck.verify import FAIL, PASS, SKIP, WARN, verify

D = Decimal

#: 54000 at 5%, 10800 at 12%, 2400 at 18% = 4428 of tax on 67200.
LINES = [
    ParsedLine(serial="1", description="Cotton Fabric 40s", hsn="5208",
               qty=D("120"), rate=D("450.00"), taxable=D("54000.00"),
               gst_rate=D("5")),
    ParsedLine(serial="2", description="Polyester Thread", hsn="5402",
               qty=D("60"), rate=D("180.00"), taxable=D("10800.00"),
               gst_rate=D("12")),
    ParsedLine(serial="3", description="Packaging Material", hsn="3923",
               qty=D("25"), rate=D("96.00"), taxable=D("2400.00"),
               gst_rate=D("18")),
]


def make_invoice(**overrides) -> Invoice:
    """A correct intra-state invoice, with fields overridable per test."""
    values = dict(
        source="test.pdf",
        supplier_name="Shreeji Trading Company",
        supplier_gstin="24AAPFU0939F1Z1",          # Gujarat
        buyer_name="Patel Traders",
        buyer_gstin="24AABCP5555F1ZK",             # also Gujarat
        number="STC/2026-27/0483",
        date="18 October 2026",
        place_of_supply="Gujarat (24)",
        # A deep copy: tests mutate line items, and a shared object
        # would leak one test's mistake into the next.
        lines=copy.deepcopy(LINES),
        taxable_value=D("67200.00"),
        cgst=D("2214.00"),
        sgst=D("2214.00"),
        igst=D("0.00"),
        round_off=D("0.00"),
        total=D("71628.00"),
        words="Seventy One Thousand Six Hundred Twenty Eight Only",
        words_amount=D("71628"),
    )
    values.update(overrides)
    return Invoice(**values)


def by_key(report, key):
    for check in report.checks:
        if check.key == key:
            return check
    raise AssertionError(f"no check called {key}")


class CleanInvoiceTests(unittest.TestCase):

    def test_everything_passes(self):
        report = verify(make_invoice())
        self.assertEqual(report.verdict, "CLEAN", [str(c) for c in report.failures])
        self.assertTrue(report.passed)

    def test_check_count(self):
        self.assertEqual(len(verify(make_invoice()).checks), 12)


class LineMathTests(unittest.TestCase):

    def test_quantity_times_rate_must_equal_taxable(self):
        invoice = make_invoice()
        invoice.lines[0].taxable = D("55000.00")
        check = by_key(verify(invoice), "line_math")
        self.assertEqual(check.status, FAIL)
        self.assertIn("54,000.00", check.detail)
        self.assertIn("55,000.00", check.detail)

    def test_a_line_without_a_rate_is_skipped_not_failed(self):
        invoice = make_invoice()
        invoice.lines[1].rate = None
        self.assertEqual(by_key(verify(invoice), "line_math").status, PASS)

    def test_no_lines_at_all_is_a_skip(self):
        invoice = make_invoice(lines=[])
        self.assertEqual(by_key(verify(invoice), "line_math").status, SKIP)


class LineSumTests(unittest.TestCase):

    def test_lines_must_add_up_to_the_taxable_value(self):
        invoice = make_invoice(taxable_value=D("67205.00"), total=D("71633.00"))
        check = by_key(verify(invoice), "lines_sum_taxable")
        self.assertEqual(check.status, FAIL)
        self.assertIn("difference", check.detail)

    def test_one_rupee_of_slack_is_allowed(self):
        """Rounding per line against rounding at the end differs by paise."""
        invoice = make_invoice(taxable_value=D("67201.00"), total=D("71629.00"))
        self.assertEqual(by_key(verify(invoice), "lines_sum_taxable").status, PASS)


class TaxTests(unittest.TestCase):

    def test_the_tax_must_match_what_the_lines_imply(self):
        """The headline case: a total that reconciles, and an invoice still wrong.

        67200 taxable, 4440 of tax and a 71640 total add up exactly. The lines
        imply 4428. A checker that only compares the total passes this.
        """
        invoice = make_invoice(cgst=D("2226.00"), sgst=D("2214.00"),
                               total=D("71640.00"), words_amount=D("71640"),
                               words="Seventy One Thousand Six Hundred Forty Only")
        report = verify(invoice)

        self.assertEqual(by_key(report, "total_reconciles").status, PASS,
                         "the total is supposed to reconcile in this sample")
        self.assertEqual(by_key(report, "tax_matches_lines").status, FAIL)
        self.assertEqual(by_key(report, "tax_split").status, FAIL)
        self.assertEqual(report.verdict, "BROKEN")

    def test_cgst_must_equal_sgst(self):
        invoice = make_invoice(cgst=D("2238.00"), sgst=D("2214.00"),
                               total=D("71652.00"), words_amount=D("71652"))
        check = by_key(verify(invoice), "tax_split")
        self.assertEqual(check.status, FAIL)
        self.assertIn("not equal", check.detail)

    def test_igst_and_cgst_together_is_an_error(self):
        invoice = make_invoice(igst=D("100.00"), total=D("71728.00"))
        check = by_key(verify(invoice), "tax_split")
        self.assertEqual(check.status, FAIL)
        self.assertIn("both", check.detail)

    def test_no_tax_at_all_is_a_skip(self):
        invoice = make_invoice(cgst=None, sgst=None, igst=None, total=D("67200.00"),
                               words_amount=D("67200"))
        self.assertEqual(by_key(verify(invoice), "tax_split").status, SKIP)


class PlaceOfSupplyTests(unittest.TestCase):

    def test_inter_state_must_use_igst(self):
        invoice = make_invoice(place_of_supply="Maharashtra (27)")
        check = by_key(verify(invoice), "place_of_supply")
        self.assertEqual(check.status, FAIL)
        self.assertIn("IGST", check.detail)

    def test_intra_state_must_not_use_igst(self):
        invoice = make_invoice(cgst=D("0.00"), sgst=D("0.00"), igst=D("4428.00"))
        self.assertEqual(by_key(verify(invoice), "place_of_supply").status, FAIL)

    def test_correct_inter_state(self):
        invoice = make_invoice(place_of_supply="Maharashtra (27)",
                               cgst=D("0.00"), sgst=D("0.00"), igst=D("4428.00"))
        self.assertEqual(by_key(verify(invoice), "place_of_supply").status, PASS)


class TotalTests(unittest.TestCase):

    def test_round_off_is_added_not_ignored(self):
        invoice = make_invoice(cgst=D("2214.30"), sgst=D("2214.30"),
                               round_off=D("-0.60"), total=D("71628.00"))
        self.assertEqual(by_key(verify(invoice), "total_reconciles").status, PASS)

    def test_missing_total_is_a_warning_not_a_failure(self):
        """A total the parser could not find is not proof the invoice is wrong."""
        invoice = make_invoice(total=None, words_amount=None)
        self.assertEqual(by_key(verify(invoice), "total_reconciles").status, WARN)

    def test_wrong_total(self):
        invoice = make_invoice(total=D("71630.00"))
        self.assertEqual(by_key(verify(invoice), "total_reconciles").status, FAIL)

    def test_a_paisa_of_rounding_is_not_a_finding(self):
        invoice = make_invoice(total=D("71628.01"))
        self.assertEqual(by_key(verify(invoice), "total_reconciles").status, PASS)


class WordsTests(unittest.TestCase):

    def test_words_must_agree(self):
        invoice = make_invoice(words="Seventy One Thousand Six Hundred Sixty Only",
                               words_amount=D("71660"))
        check = by_key(verify(invoice), "amount_in_words")
        self.assertEqual(check.status, FAIL)
        self.assertIn("71,660.00", check.detail)

    def test_no_words_is_a_skip(self):
        invoice = make_invoice(words="", words_amount=None)
        self.assertEqual(by_key(verify(invoice), "amount_in_words").status, SKIP)


class GstinTests(unittest.TestCase):

    def test_bad_buyer_gstin(self):
        invoice = make_invoice(buyer_gstin="27ABCPD1234E1Z5")
        check = by_key(verify(invoice), "buyer_gstin")
        self.assertEqual(check.status, FAIL)
        self.assertIn("check character", check.detail)

    def test_missing_buyer_gstin_is_not_a_failure(self):
        """Plenty of legitimate B2C bills carry no buyer GSTIN."""
        self.assertEqual(by_key(verify(make_invoice(buyer_gstin="")),
                                "buyer_gstin").status, SKIP)

    def test_missing_supplier_gstin_is_a_failure(self):
        self.assertEqual(by_key(verify(make_invoice(supplier_gstin="")),
                                "supplier_gstin").status, FAIL)


class ToleranceTests(unittest.TestCase):

    def test_sixty_paise_passes_at_one_rupee(self):
        invoice = make_invoice(cgst=D("2214.30"), sgst=D("2214.30"))
        self.assertEqual(by_key(verify(invoice), "tax_matches_lines").status, PASS)

    def test_sixty_paise_fails_at_ten_paise(self):
        invoice = make_invoice(cgst=D("2214.30"), sgst=D("2214.30"))
        report = verify(invoice, tolerance=D("0.10"))
        self.assertEqual(by_key(report, "tax_matches_lines").status, FAIL)

    def test_zero_tolerance_is_strict(self):
        invoice = make_invoice()
        report = verify(invoice, tolerance=D("0"))
        self.assertTrue(report.passed, [str(c) for c in report.failures])


class EmptyDocumentTests(unittest.TestCase):

    def test_an_empty_read_blames_nothing(self):
        """A blank file is not an invoice with a bad GSTIN."""
        report = verify(Invoice())
        self.assertEqual(report.verdict, "REVIEW")
        self.assertEqual(len(report.checks), 1)
        self.assertEqual(report.checks[0].status, WARN)
        self.assertIn("nothing that looks like an invoice", report.checks[0].detail)
        self.assertEqual(report.failures, [])

    def test_is_empty(self):
        self.assertTrue(Invoice().is_empty)
        self.assertFalse(make_invoice().is_empty)
        self.assertFalse(Invoice(supplier_gstin="24AAPFU0939F1Z1").is_empty)


class VerdictTests(unittest.TestCase):

    def test_money_failure_is_broken(self):
        invoice = make_invoice(cgst=D("3000.00"), sgst=D("3000.00"),
                               total=D("73200.00"), words_amount=D("73200"))
        self.assertEqual(verify(invoice).verdict, "BROKEN")

    def test_identity_failure_is_suspect(self):
        invoice = make_invoice(buyer_gstin="27ABCPD1234E1Z5")
        report = verify(invoice)
        self.assertEqual(report.verdict, "SUSPECT")
        self.assertFalse(report.money_failures)

    def test_warning_only_is_review(self):
        invoice = make_invoice(total=None, words_amount=None)
        self.assertEqual(verify(invoice).verdict, "REVIEW")

    def test_report_serialises(self):
        payload = verify(make_invoice()).to_dict()
        self.assertEqual(payload["verdict"], "CLEAN")
        self.assertEqual(len(payload["checks"]), 12)
        self.assertIn("invoice", payload)


if __name__ == "__main__":
    unittest.main()
