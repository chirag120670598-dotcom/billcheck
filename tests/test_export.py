"""Export shapes: JSON, register CSV, line CSV, review sheet."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from decimal import Decimal

from tests.test_verify import make_invoice

from billcheck.export import (LINE_COLUMNS, REGISTER_COLUMNS, line_rows,
                              register_row, review_sheet, to_json,
                              write_lines, write_register)
from billcheck.verify import verify

D = Decimal


def broken_report():
    invoice = make_invoice(cgst=D("2226.00"), sgst=D("2214.00"),
                           total=D("71640.00"), words_amount=D("71640"),
                           words="Seventy One Thousand Six Hundred Forty Only")
    return verify(invoice)


class RegisterRowTests(unittest.TestCase):

    def test_row_shape(self):
        row = register_row(verify(make_invoice()))
        self.assertEqual(list(row.keys()), REGISTER_COLUMNS)

    def test_amounts_have_no_thousands_separator(self):
        """A comma inside a number would split the CSV column."""
        row = register_row(verify(make_invoice()))
        self.assertEqual(row["taxable_value"], "67200.00")
        self.assertEqual(row["invoice_total"], "71628.00")

    def test_date_is_iso(self):
        self.assertEqual(register_row(verify(make_invoice()))["voucher_date"],
                         "2026-10-18")

    def test_failures_are_summarised(self):
        row = register_row(broken_report())
        self.assertEqual(row["verdict"], "BROKEN")
        self.assertIn("Tax charged", row["failures"])

    def test_missing_values_are_blank_not_none(self):
        invoice = make_invoice(cess=None, round_off=None)
        row = register_row(verify(invoice))
        self.assertEqual(row["cess"], "")
        self.assertEqual(row["round_off"], "")


class LineRowTests(unittest.TestCase):

    def test_one_row_per_line(self):
        rows = line_rows(verify(make_invoice()))
        self.assertEqual(len(rows), 3)
        self.assertEqual(list(rows[0].keys()), LINE_COLUMNS)
        self.assertEqual(rows[0]["description"], "Cotton Fabric 40s")
        self.assertEqual(rows[0]["taxable_value"], "54000.00")


class CsvWritingTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        for name in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, name))
        os.rmdir(self.dir)

    def test_register_round_trips_through_csv(self):
        path = os.path.join(self.dir, "r.csv")
        write_register([verify(make_invoice()), broken_report()], path)
        with open(path, encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["verdict"], "CLEAN")
        self.assertEqual(rows[1]["verdict"], "BROKEN")

    def test_a_description_with_a_comma_survives(self):
        invoice = make_invoice()
        invoice.lines[0].description = "Fabric, dyed, 40s"
        path = os.path.join(self.dir, "l.csv")
        write_lines([verify(invoice)], path)
        with open(path, encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["description"], "Fabric, dyed, 40s")


class JsonTests(unittest.TestCase):

    def test_structure(self):
        payload = json.loads(to_json([verify(make_invoice())]))
        self.assertEqual(payload["tool"], "billcheck")
        invoice = payload["invoices"][0]
        self.assertEqual(invoice["verdict"], "CLEAN")
        self.assertEqual(invoice["invoice"]["invoice_number"], "STC/2026-27/0483")
        self.assertEqual(len(invoice["checks"]), 12)
        # Money is serialised as a string so it cannot become a float.
        self.assertEqual(invoice["invoice"]["totals"]["total"], "71628.00")

    def test_unicode_is_not_escaped(self):
        invoice = make_invoice(supplier_name="श्रीजी ट्रेडिंग कंपनी")
        text = to_json([verify(invoice)])
        self.assertIn("श्रीजी", text)


class ReviewSheetTests(unittest.TestCase):

    def test_mentions_the_failure_and_its_reason(self):
        text = review_sheet([broken_report()])
        self.assertIn("Needs attention", text)
        self.assertIn("BROKEN", text)
        self.assertIn("4,440.00", text)

    def test_states_the_limit_of_the_tool(self):
        text = review_sheet([verify(make_invoice())])
        self.assertIn("cannot tell you whether", text)

    def test_lists_the_clean_ones_too(self):
        text = review_sheet([verify(make_invoice()), broken_report()])
        self.assertIn("Nothing found", text)
        self.assertIn("STC/2026-27/0483", text)


if __name__ == "__main__":
    unittest.main()
