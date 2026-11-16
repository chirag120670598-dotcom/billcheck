"""The landing page has a small checker in it, and it must agree with this one.

Nearly every number read on that page comes from the same rules as
`billcheck.verify`. A page that quietly disagrees with the tool is worse than no
page, so its arithmetic is tested here -- through node, when node is installed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class SiteScriptTests(unittest.TestCase):

    def test_site_checker_matches_the_python_rules(self):
        result = subprocess.run(
            ["node", os.path.join(ROOT, "tools", "check_site.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0,
                         result.stdout + result.stderr)
        self.assertIn("site ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
