"""The command line: exit codes, output files, and bad input.

The exit code is the contract. A script that runs billcheck over a folder has to
be able to trust that 0 means clean, 1 means something failed, and 2 means the
run itself broke -- without parsing any text.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

from tests.sample_support import ROOT, build_samples, sample_path

CLEAN = sample_path("clean_interstate.pdf")
BROKEN = sample_path("broken_tax_split.pdf")
TEXT_CLEAN = sample_path("plain_intrastate.txt")


def run(*args, **kwargs):
    return subprocess.run([sys.executable, "-m", "billcheck", *args],
                          cwd=ROOT, capture_output=True, text=True,
                          timeout=180, **kwargs)


class CliTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not build_samples():
            raise unittest.SkipTest("sample invoices are not available")

    def test_clean_invoice_exits_zero(self):
        result = run(TEXT_CLEAN, "--no-colour")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLEAN", result.stdout)

    def test_failing_invoice_exits_one(self):
        result = run(BROKEN, "--no-colour")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("BROKEN", result.stdout)
        self.assertIn("Tax charged equals the tax the line rates imply",
                      result.stdout)

    def test_missing_file_exits_two(self):
        result = run("does-not-exist.pdf", "--no-colour")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no such file", result.stderr)

    def test_a_bad_file_does_not_stop_the_good_ones(self):
        result = run("does-not-exist.pdf", TEXT_CLEAN, "--no-colour")
        self.assertEqual(result.returncode, 2)
        self.assertIn("CLEAN", result.stdout)

    def test_quiet_writes_nothing(self):
        result = run(TEXT_CLEAN, "--quiet")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_tolerance_must_be_a_number(self):
        result = run(TEXT_CLEAN, "--tolerance", "lots")
        self.assertEqual(result.returncode, 2)
        self.assertIn("is not a number", result.stderr)

    def test_negative_tolerance_is_refused(self):
        result = run(TEXT_CLEAN, "--tolerance", "-1")
        self.assertEqual(result.returncode, 2)

    def test_version(self):
        result = run("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("billcheck", result.stdout)

    def test_usage_without_a_file(self):
        result = run()
        self.assertEqual(result.returncode, 2)


class DirectoryTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not build_samples():
            raise unittest.SkipTest("sample invoices are not available")

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "one.txt"), "w", encoding="utf-8") as h:
            h.write(open(TEXT_CLEAN, encoding="utf-8").read())

    def tearDown(self):
        for name in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, name))
        os.rmdir(self.dir)

    def test_a_directory_means_the_invoices_in_it(self):
        result = run(self.dir, "--no-colour")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("one.txt", result.stdout)
        self.assertIn("CLEAN", result.stdout)

    def test_a_directory_with_nothing_in_it_is_an_error(self):
        empty = tempfile.mkdtemp()
        try:
            result = run(empty, "--no-colour")
            self.assertEqual(result.returncode, 2)
            self.assertIn("no PDF or text invoices", result.stderr)
        finally:
            os.rmdir(empty)

    def test_non_invoice_files_are_ignored(self):
        with open(os.path.join(self.dir, "notes.md"), "w", encoding="utf-8") as h:
            h.write("# not an invoice")
        result = run(self.dir, "--no-colour")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("notes.md", result.stdout)


class OutputFileTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not build_samples():
            raise unittest.SkipTest("sample invoices are not available")

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        for name in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, name))
        os.rmdir(self.dir)

    def test_json(self):
        path = os.path.join(self.dir, "report.json")
        run(TEXT_CLEAN, "--quiet", "--json", path)
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["schema"], 1)
        self.assertEqual(payload["invoices"][0]["verdict"], "CLEAN")

    def test_csv_register(self):
        path = os.path.join(self.dir, "register.csv")
        run(TEXT_CLEAN, BROKEN, "--quiet", "--csv", path)
        with open(path, encoding="utf-8") as handle:
            rows = handle.read().strip().splitlines()
        self.assertEqual(len(rows), 3)                     # header + 2 invoices
        self.assertTrue(rows[0].startswith("source,verdict,voucher_date"))
        self.assertIn("5733.00", rows[1])          # the plain text invoice
        self.assertIn("71640.00", rows[2])         # the broken one

    def test_csv_lines(self):
        path = os.path.join(self.dir, "lines.csv")
        run(TEXT_CLEAN, "--quiet", "--lines", path)
        with open(path, encoding="utf-8") as handle:
            rows = handle.read().strip().splitlines()
        self.assertEqual(len(rows), 3)                     # header + 2 lines
        self.assertIn("Cotton Fabric 40s", rows[1])

    def test_review_sheet(self):
        path = os.path.join(self.dir, "review.md")
        run(TEXT_CLEAN, BROKEN, "--quiet", "--review", path)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("# Invoice review sheet", text)
        self.assertIn("Needs attention", text)
        self.assertIn("cannot tell you whether", text)

    def test_no_output_flag_writes_no_file(self):
        result = run(TEXT_CLEAN, "--quiet")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(os.listdir(self.dir), [])


if __name__ == "__main__":
    unittest.main()
