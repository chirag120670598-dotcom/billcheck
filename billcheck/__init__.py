"""billcheck -- check whether an Indian GST invoice adds up.

    >>> from billcheck import check
    >>> report = check("invoice.pdf")
    >>> report.verdict
    'CLEAN'

The package has no dependencies for text input and needs only `pypdf` for PDFs.
"""

__version__ = "0.1.0"

from .verify import Check, Report, verify          # noqa: E402
from .parse import Invoice, ParsedLine, parse_invoice   # noqa: E402
from .money import format_inr, parse_amount, words_to_amount  # noqa: E402
from .gst import validate_gstin, gstin_valid       # noqa: E402


def check(path, *, tolerance="1.00"):
    """Read one invoice and verify it. The one-liner the README shows."""
    from decimal import Decimal
    from .pdf import read_any

    invoice = parse_invoice(read_any(path))
    if not invoice.source:
        invoice.source = str(path)
    return verify(invoice, tolerance=Decimal(str(tolerance)))


__all__ = [
    "__version__",
    "check",
    "Invoice",
    "ParsedLine",
    "parse_invoice",
    "verify",
    "Report",
    "Check",
    "parse_amount",
    "format_inr",
    "words_to_amount",
    "gstin_valid",
    "validate_gstin",
]
