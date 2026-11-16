"""Shared helpers for the tests that read the sample invoices.

The samples are generated, not committed as binaries, so they can be rebuilt
from `tools/make_samples.py` at any time. When they are missing the tests that
need them skip rather than fail: a checkout without reportlab installed should
still be able to run the other nine tenths of the suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "data", "samples")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _have(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


HAVE_PYPDF = _have("pypdf")
HAVE_REPORTLAB = _have("reportlab")


def sample_path(name: str) -> str:
    return os.path.join(SAMPLES, name)


def samples_present(*names: str) -> bool:
    return all(os.path.exists(sample_path(name)) for name in names)


def build_samples() -> bool:
    """Generate the samples if they are missing. True when they are available."""
    needed = ("clean_interstate.pdf", "broken_tax_split.pdf", "no_total.pdf")
    if samples_present(*needed):
        return True
    if not HAVE_REPORTLAB:
        return False
    result = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_samples.py")],
                            cwd=ROOT, capture_output=True, text=True)
    return result.returncode == 0 and samples_present(*needed)


requires_pdf = unittest.skipUnless(HAVE_PYPDF, "pypdf is not installed")
requires_samples = unittest.skipUnless(
    build_samples(), "sample invoices could not be generated (reportlab missing)")
