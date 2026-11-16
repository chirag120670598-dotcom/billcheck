"""Recovering the GST rate when the invoice does not print one.

The search must return exactly one answer or say that it cannot. A tool that
picks the first combination that happens to add up is worse than one that
admits three of them do.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from billcheck.infer import STANDARD_RATES, infer_line_rates
from billcheck.parse import ParsedLine

D = Decimal


def line(taxable, rate=None):
    return ParsedLine(taxable=D(taxable), gst_rate=rate and D(rate))


class InferenceTests(unittest.TestCase):

    def test_a_single_rate_is_found(self):
        result = infer_line_rates([line("5000")], D("600"))     # 12%
        self.assertEqual(result.status, "unique")
        self.assertEqual(result.rates, [D("12")])

    def test_two_rates_are_separated(self):
        # 105250 at 5% = 5262.50, 18000 at 18% = 3240, total 8502.50
        result = infer_line_rates([line("105250"), line("18000")], D("8502.50"))
        self.assertEqual(result.status, "unique")
        self.assertEqual(result.rates, [D("5"), D("18")])

    def test_a_tax_that_no_rate_explains(self):
        result = infer_line_rates([line("5000")], D("777.77"))
        self.assertEqual(result.status, "none")
        self.assertIsNone(result.rates)

    def test_an_ambiguous_tax_says_so(self):
        # Two identical lines: 0% on the first and 5% on the second fits, and
        # so does 5% then 0%. Different answers, same total.
        result = infer_line_rates([line("10000"), line("10000")], D("500"))
        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.rates)

    def test_nothing_to_search(self):
        self.assertEqual(infer_line_rates([], D("10")).status, "skipped")
        self.assertEqual(
            infer_line_rates([ParsedLine()], D("10")).status, "skipped")
        self.assertEqual(infer_line_rates([line("100")], None).status, "skipped")

    def test_too_many_lines_is_skipped_not_slow(self):
        lots = [line("100") for _ in range(20)]
        result = infer_line_rates(lots, D("500"))
        self.assertEqual(result.status, "skipped")
        self.assertIn("more than this search", result.detail)

    def test_nil_rated_line(self):
        result = infer_line_rates([line("1000")], D("0"))
        # 0% on its own is a fit, but so is nothing at all on a nil invoice;
        # either way the answer that must never appear is a made-up rate.
        self.assertIn(result.status, ("unique", "ambiguous"))
        if result.status == "unique":
            self.assertEqual(result.rates, [D("0")])

    def test_tolerance_is_respected(self):
        tight = infer_line_rates([line("5000")], D("600.40"),
                                 tolerance=D("0"))
        loose = infer_line_rates([line("5000")], D("600.40"),
                                 tolerance=D("1.00"))
        self.assertEqual(tight.status, "none")
        self.assertEqual(loose.status, "unique")

    def test_rates_have_no_absurd_values(self):
        for rate in STANDARD_RATES:
            self.assertLessEqual(rate, D("28"))
            self.assertGreaterEqual(rate, D("0"))


if __name__ == "__main__":
    unittest.main()
