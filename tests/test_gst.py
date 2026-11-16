"""GSTIN validation: the checksum, the state code, the PAN.

The check character is the whole reason this tool exists as more than a parser.
A GSTIN that is one character wrong looks completely normal -- same length, same
shape, same format -- and only arithmetic tells you.
"""

from __future__ import annotations

import unittest

from billcheck.gst import (GSTIN_PATTERN, STATE_CODES, gstin_check_character,
                           gstin_valid, parse_gstin, state_code_from_name,
                           state_name, validate_gstin)


class CheckCharacterTests(unittest.TestCase):

    def test_known_valid_gstin(self):
        ok, reason = validate_gstin("27AAPFU0939F1ZV")
        self.assertTrue(ok, reason)
        self.assertIn("Maharashtra", reason)

    def test_computed_character_matches_known_values(self):
        for gstin in ("27AAPFU0939F1ZV", "24ABCPD1234E1ZK", "29AABCU9603R1ZJ"):
            self.assertEqual(gstin_check_character(gstin[:14]), gstin[14], gstin)

    def test_wrong_last_character_is_named(self):
        ok, reason = validate_gstin("27AAPFU0939F1ZA")
        self.assertFalse(ok)
        self.assertEqual(reason, "check character should be V, printed A")

    def test_garbage_last_character(self):
        ok, reason = validate_gstin("27ABCPD1234E1Z5")
        self.assertFalse(ok)
        self.assertIn("check character", reason)

    def test_wrong_length(self):
        ok, reason = validate_gstin("27AAPFU0939F1")
        self.assertFalse(ok)
        self.assertIn("a GSTIN has 15", reason)

    def test_empty(self):
        self.assertFalse(gstin_valid(""))
        self.assertFalse(gstin_valid(None))

    def test_lowercase_is_accepted(self):
        """GSTINs are printed in caps but exported in lower case constantly."""
        self.assertTrue(gstin_valid("27aapfu0939f1zv"))

    def test_spaces_inside_are_ignored(self):
        self.assertTrue(gstin_valid("27 AAPFU 0939F1ZV"))

    def test_bad_state_code(self):
        ok, reason = validate_gstin("39AAPFU0939F1Z" + gstin_check_character("39AAPFU0939F1Z"))
        self.assertFalse(ok)
        self.assertIn("state code", reason)

    def test_pan_shape(self):
        ok, reason = validate_gstin("27ABCDE1234F1Z" + gstin_check_character("27ABCDE1234F1Z"))
        self.assertFalse(ok)
        self.assertIn("PAN", reason)


class StateTests(unittest.TestCase):

    def test_state_name_from_code(self):
        self.assertEqual(state_name("24"), "Gujarat")
        self.assertEqual(state_name("27"), "Maharashtra")

    def test_code_from_name_with_number(self):
        self.assertEqual(state_code_from_name("Gujarat (24)"), "24")
        self.assertEqual(state_code_from_name("Maharashtra (27)"), "27")

    def test_code_from_bare_name(self):
        self.assertEqual(state_code_from_name("Gujarat"), "24")
        self.assertEqual(state_code_from_name("maharashtra"), "27")

    def test_old_and_new_names(self):
        # Both names appear on invoices from before and after the 2020 change.
        self.assertEqual(state_code_from_name("Orissa"), "21")
        self.assertEqual(state_code_from_name("Odisha"), "21")

    def test_unknown(self):
        self.assertIsNone(state_code_from_name("Atlantis"))
        self.assertIsNone(state_code_from_name(""))

    def test_all_38_entries_are_two_digit_strings(self):
        self.assertGreaterEqual(len(STATE_CODES), 38)
        for code, name in STATE_CODES.items():
            self.assertRegex(code, r"^\d{2}$")
            self.assertTrue(name)


class ParseGstinTests(unittest.TestCase):

    def test_parts(self):
        parts = parse_gstin("27AAPFU0939F1ZV")
        self.assertEqual(parts["state_code"], "27")
        self.assertEqual(parts["pan"], "AAPFU0939F")
        self.assertEqual(parts["entity"], "1")

    def test_pattern_finds_one_in_text(self):
        match = GSTIN_PATTERN.search("GSTIN: 24AAPFU0939F1Z1 dated 18 Oct")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "24AAPFU0939F1Z1")

    def test_pattern_does_not_run_past_the_gstin(self):
        """The old pattern swallowed the character after the GSTIN."""
        match = GSTIN_PATTERN.search("Buyer GSTIN: 27ABCPD1234E1ZK Place of Supply")
        self.assertEqual(match.group(1), "27ABCPD1234E1ZK")


if __name__ == "__main__":
    unittest.main()
