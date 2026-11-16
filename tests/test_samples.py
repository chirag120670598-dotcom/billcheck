"""The golden table: every sample invoice, and exactly what must be said about it.

This is the test that catches "the tool still runs" regressions. A parser change
that quietly breaks one invoice's arithmetic produces a passing suite in every
other file; here it produces a mismatch, by name.

Each sample is checked for three things: the verdict, which checks failed, and
which checks warned. Nothing about the wording, because wording is allowed to
improve.
"""

from __future__ import annotations

import unittest

from tests.sample_support import (HAVE_PYPDF, build_samples, sample_path,
                                  samples_present)

from billcheck.parse import parse_invoice
from billcheck.pdf import read_any
from billcheck.verify import verify

#: file -> (verdict, failed check keys, warned check keys)
GOLDEN = {
    "clean_interstate.pdf": ("CLEAN", set(), set()),
    "clean_intrastate.pdf": ("CLEAN", set(), set()),
    "round_off.pdf": ("CLEAN", set(), set()),
    "plain_intrastate.txt": ("CLEAN", set(), set()),

    # The headline: the total adds up and the invoice is still wrong.
    "broken_tax_split.pdf": ("BROKEN",
                             {"tax_matches_lines", "tax_split"}, set()),

    # One line's taxable is not its quantity times its rate.
    "broken_line_math.pdf": ("BROKEN", {"line_math"}, set()),

    # The buyer's GSTIN fails its check digit; nothing else is wrong.
    "broken_gstin.pdf": ("SUSPECT", {"buyer_gstin"}, set()),

    # The words are short by thirty-two rupees.
    "broken_words.pdf": ("SUSPECT", {"amount_in_words"}, set()),

    # Devanagari digits and labels read correctly, but there is no line table.
    "devanagari.txt": ("REVIEW", set(), {"line_items"}),

    # A truncated invoice: no total to check against.
    "no_total.pdf": ("REVIEW", set(), {"total_reconciles"}),

    # A different house style with no rate column: the rates are recovered from
    # the totals and reported as an inference, not as something the bill says.
    "layout_variant.pdf": ("REVIEW", set(), {"tax_matches_lines"}),
}

PDF_SAMPLES = {"clean_interstate.pdf", "clean_intrastate.pdf", "round_off.pdf",
               "broken_tax_split.pdf", "broken_line_math.pdf", "broken_gstin.pdf",
               "broken_words.pdf", "no_total.pdf", "layout_variant.pdf"}


class GoldenTableTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not build_samples():
            raise unittest.SkipTest("sample invoices are not available; "
                                    "install reportlab and run tools/make_samples.py")

    def _report(self, name):
        if name in PDF_SAMPLES and not HAVE_PYPDF:
            self.skipTest("pypdf is not installed")
        if not samples_present(name):
            self.skipTest(f"{name} was not generated")
        return verify(parse_invoice(read_any(sample_path(name))))

    def test_every_sample_matches_its_row(self):
        for name, (verdict, failures, warnings) in GOLDEN.items():
            with self.subTest(sample=name):
                report = self._report(name)
                self.assertEqual(
                    report.verdict, verdict,
                    f"{name}: {[str(c) for c in report.failures]}")
                self.assertEqual({c.key for c in report.failures}, failures,
                                 f"{name} failures")
                self.assertEqual({c.key for c in report.warnings}, warnings,
                                 f"{name} warnings")

    def test_the_clean_samples_are_genuinely_clean(self):
        """Guards against a sample drifting into being wrong by accident."""
        for name in ("clean_interstate.pdf", "clean_intrastate.pdf", "round_off.pdf"):
            with self.subTest(sample=name):
                report = self._report(name)
                self.assertEqual(len(report.checks), 12)
                not_passing = [str(c) for c in report.checks if c.status != "pass"]
                self.assertEqual(not_passing, [])

    def test_totals_are_read_at_full_value_not_truncated(self):
        """Regression: totals came out a hundred times too small."""
        invoice = parse_invoice(read_any(sample_path("clean_interstate.pdf")))
        self.assertEqual(str(invoice.taxable_value), "67200.00")
        self.assertEqual(str(invoice.total), "71628.00")
        self.assertEqual(len(invoice.lines), 3)

    def test_the_line_items_reconcile_on_the_clean_sample(self):
        invoice = parse_invoice(read_any(sample_path("clean_interstate.pdf")))
        for line in invoice.lines:
            self.assertEqual(line.qty * line.rate, line.taxable,
                             f"line {line.serial}")


if __name__ == "__main__":
    unittest.main()
