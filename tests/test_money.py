"""Amount parsing and formatting.

The first test in this file is a regression test for the worst bug this project
has had. The obvious regex for "a number, possibly with thousands separators"
is two alternatives, the grouped branch first:

    -?\\d{1,3}(?:,\\d{2,3})*(?:\\.\\d+)?|-?\\d+(?:\\.\\d+)?

and it silently reads "67200.00" as 672, because the grouped branch matches the
first three digits and a regex alternation does not need to reach the end of the
string. Every total on every invoice came out a hundred times too small. The
test stays here so the pattern can never go back.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from billcheck.money import (format_inr, is_numeric_cell, normalise_digits,
                             parse_amount, quantise, to_decimal,
                             words_to_amount)


class ParseAmountTests(unittest.TestCase):

    def test_comma_less_amounts_are_not_truncated(self):
        """Regression: bare numbers used to lose their last digits."""
        self.assertEqual(parse_amount("67200.00"), Decimal("67200.00"))
        self.assertEqual(parse_amount("71664.00"), Decimal("71664.00"))
        self.assertEqual(parse_amount("54000"), Decimal("54000"))
        self.assertEqual(parse_amount("2400"), Decimal("2400"))
        self.assertEqual(parse_amount("123456789"), Decimal("123456789"))

    def test_indian_grouping(self):
        self.assertEqual(parse_amount("1,23,456.00"), Decimal("123456.00"))
        self.assertEqual(parse_amount("12,34,567.89"), Decimal("1234567.89"))
        self.assertEqual(parse_amount("2,400.00"), Decimal("2400.00"))

    def test_western_grouping_also_reads(self):
        """Exporters and English-language software print 1,234,567.89."""
        self.assertEqual(parse_amount("1,234,567.89"), Decimal("1234567.89"))

    def test_decimals(self):
        self.assertEqual(parse_amount("450.00"), Decimal("450.00"))
        self.assertEqual(parse_amount("0.05"), Decimal("0.05"))
        self.assertEqual(parse_amount("0.5"), Decimal("0.5"))
        # parse_amount finds the number *in* a string, so ".5" reads as 5 and
        # "Cotton Fabric 40s" reads as 40. That is deliberate: it is what makes
        # "Taxable Value: 67200.00" work. Anything that needs to know whether a
        # cell is a number must ask is_numeric_cell instead.
        self.assertEqual(parse_amount(".5"), Decimal("5"))
        self.assertFalse(is_numeric_cell(".5"))

    def test_currency_decoration(self):
        self.assertEqual(parse_amount("Rs. 1,23,456/-"), Decimal("123456"))
        self.assertEqual(parse_amount("INR 2400.00"), Decimal("2400.00"))
        self.assertEqual(parse_amount("₹ 2,400.50"), Decimal("2400.50"))

    def test_negative_in_parentheses(self):
        self.assertEqual(parse_amount("(1,234.00)"), Decimal("-1234.00"))
        self.assertEqual(parse_amount("-0.60"), Decimal("-0.60"))

    def test_devanagari_digits(self):
        self.assertEqual(parse_amount("२,४००.००"), Decimal("2400.00"))
        self.assertEqual(parse_amount("७१,६२८"), Decimal("71628"))

    def test_garbage_returns_none(self):
        for text in ("", "   ", "nil", "N/A", "-", "Total"):
            self.assertIsNone(parse_amount(text), text)


class IsNumericCellTests(unittest.TestCase):

    def test_digits_inside_a_description_do_not_make_it_a_number(self):
        self.assertFalse(is_numeric_cell("Cotton Fabric 40s"))
        self.assertFalse(is_numeric_cell("HSN 5208 grey"))
        self.assertFalse(is_numeric_cell("GST%"))

    def test_plain_numbers_are_numbers(self):
        for cell in ("1", "5208", "120", "450.00", "2,400.00", "₹450"):
            self.assertTrue(is_numeric_cell(cell), cell)

    def test_empty_is_not_a_number(self):
        self.assertFalse(is_numeric_cell(""))
        self.assertFalse(is_numeric_cell("   "))


class WordsToAmountTests(unittest.TestCase):

    def test_plain(self):
        self.assertEqual(
            words_to_amount("Seventy One Thousand Six Hundred Sixty Four Only"),
            Decimal("71664"))

    def test_lakh_and_crore(self):
        self.assertEqual(
            words_to_amount("One Crore Twenty Three Lakh Forty Five Thousand "
                            "Six Hundred Seventy Eight"),
            Decimal("12345678"))
        self.assertEqual(
            words_to_amount("Twelve Lakh Thirty Four Thousand Rupees and "
                            "Fifty Paise"),
            Decimal("1234000.50"))

    def test_paise(self):
        self.assertEqual(
            words_to_amount("One Crore Twenty Three Lakh Forty Five Thousand "
                            "Six Hundred Seventy Eight Rupees and Five Paise"),
            Decimal("12345678.05"))

    def test_indian_style_hundred(self):
        """Indian invoices write 1,25,000 as 'One Lakh Twenty Five Thousand'."""
        self.assertEqual(words_to_amount("One Lakh Twenty Five Thousand Only"),
                         Decimal("125000"))
        self.assertEqual(words_to_amount("Two Thousand Five Hundred Only"),
                         Decimal("2500"))

    def test_missing_only_suffix(self):
        self.assertEqual(words_to_amount("Five Thousand Seven Hundred Thirty Three"),
                         Decimal("5733"))

    def test_empty(self):
        self.assertIsNone(words_to_amount(""))
        self.assertIsNone(words_to_amount(None))


class FormatTests(unittest.TestCase):

    def test_indian_grouping(self):
        self.assertEqual(format_inr(Decimal("1234567.5")), "12,34,567.50")
        self.assertEqual(format_inr(Decimal("71628")), "71,628.00")
        self.assertEqual(format_inr(Decimal("999")), "999.00")
        self.assertEqual(format_inr(Decimal("-0.60")), "-0.60")

    def test_lakh_boundary(self):
        self.assertEqual(format_inr(Decimal("100000")), "1,00,000.00")
        self.assertEqual(format_inr(Decimal("1000000")), "10,00,000.00")
        self.assertEqual(format_inr(Decimal("10000000")), "1,00,00,000.00")

    def test_quantise_rounds_to_paise(self):
        self.assertEqual(quantise(Decimal("10.005")), Decimal("10.01"))
        self.assertEqual(quantise(Decimal("10.004")), Decimal("10.00"))

    def test_to_decimal_rejects_nonsense(self):
        self.assertIsNone(to_decimal("abc"))
        self.assertEqual(to_decimal("12.5"), Decimal("12.5"))
        self.assertEqual(to_decimal(12.5), Decimal("12.5"))


class DigitTests(unittest.TestCase):

    def test_normalise(self):
        self.assertEqual(normalise_digits("२,४००"), "2,400")
        self.assertEqual(normalise_digits("૨૪૦૦"), "2400")     # Gujarati
        self.assertEqual(normalise_digits("٢٤٠٠"), "2400")     # Arabic-Indic


if __name__ == "__main__":
    unittest.main()
