"""The command line. `billcheck invoice.pdf`.

Exit codes carry the answer, so this works in a shell loop or a CI step:

    0   every invoice passed every check
    1   at least one invoice failed a check
    2   the run itself went wrong (no such file, unreadable PDF, ...)

The human output goes to stdout and is meant to be read. Everything a machine
needs goes to a file, through --json / --csv / --lines / --review.
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal, InvalidOperation
from glob import glob
from typing import List, Sequence

from . import __version__
from .export import write_json, write_lines, write_register, review_sheet
from .parse import parse_invoice
from .pdf import NoTextLayer, PdfUnavailable, read_any
from .verify import Report, verify

__all__ = ["main", "render_report"]

_MARK = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "--"}
_COLOUR = {"pass": "\033[32m", "fail": "\033[31m", "warn": "\033[33m",
           "skip": "\033[90m", "head": "\033[1m", "off": "\033[0m"}

_VERDICT_LINE = {
    "CLEAN": "no problems found",
    "REVIEW": "passes the arithmetic, but read the warnings",
    "SUSPECT": "a field on this invoice cannot be trusted",
    "BROKEN": "the arithmetic on this invoice is wrong",
}


def _paint(text: str, key: str, colour: bool) -> str:
    if not colour:
        return text
    return _COLOUR.get(key, "") + text + _COLOUR["off"]


def render_report(report: Report, *, colour: bool = False, verbose: bool = False) -> str:
    invoice = report.invoice
    name = os.path.basename(invoice.source) if invoice.source else "invoice"
    out: List[str] = []

    header = f"{name}"
    if invoice.number:
        header += f"  ·  {invoice.number}"
    if invoice.total is not None:
        from .money import format_inr
        header += f"  ·  {format_inr(invoice.total)}"
    out.append(_paint(header, "head", colour))

    verdict = report.verdict
    colour_key = {"CLEAN": "pass", "REVIEW": "warn", "SUSPECT": "warn",
                  "BROKEN": "fail"}[verdict]
    out.append(f"  {_paint(verdict, colour_key, colour)} — "
               f"{_VERDICT_LINE[verdict]}")

    shown = [c for c in report.sorted_checks()
             if c.status in ("fail", "warn") or verbose]
    for check in shown:
        mark = _paint(_MARK[check.status], check.status, colour)
        out.append(f"    {mark}  {check.title}")
        if check.detail:
            out.append(f"          {check.detail}")

    if not shown:
        out.append(f"    {len(report.checks)} checks, all clear")
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="billcheck",
        description="Check whether an Indian GST invoice adds up.",
        epilog="Exit code 0 means every invoice passed, 1 means something "
               "failed, 2 means the run itself went wrong.")
    parser.add_argument("paths", nargs="+", metavar="INVOICE",
                        help="PDF or text file(s) to check")
    parser.add_argument("--json", metavar="PATH", help="write the full report as JSON")
    parser.add_argument("--csv", metavar="PATH",
                        help="write one row per invoice, register-shaped")
    parser.add_argument("--lines", metavar="PATH",
                        help="write one row per line item")
    parser.add_argument("--review", metavar="PATH",
                        help="write a Markdown review sheet")
    parser.add_argument("--tolerance", default="1.00", metavar="RUPEES",
                        help="allowed rounding difference, in rupees (default 1.00)")
    parser.add_argument("--quiet", action="store_true",
                        help="print nothing, only set the exit code")
    parser.add_argument("--verbose", action="store_true",
                        help="show the checks that passed too")
    parser.add_argument("--no-colour", "--no-color", dest="no_colour",
                        action="store_true", help="plain text output")
    parser.add_argument("--version", action="version",
                        version=f"billcheck {__version__}")
    return parser


#: What counts as an invoice when a directory is passed.
READABLE = (".pdf", ".txt", ".text")


def expand_paths(paths: Sequence[str]) -> tuple:
    """Turn directories into the invoice files inside them.

    ``billcheck invoices/`` is what people type, so it has to work. One level
    only: a recursive walk would pick up archived invoices from 2019 that nobody
    asked about, and silently checking the wrong half of a folder is worse than
    being explicit.
    """
    expanded, errors = [], 0
    for path in paths:
        if not os.path.isdir(path):
            expanded.append(path)
            continue
        found = sorted(p for p in glob(os.path.join(path, "*"))
                       if p.lower().endswith(READABLE))
        if not found:
            print(f"billcheck: {path}: directory contains no PDF or text invoices",
                  file=sys.stderr)
            errors += 1
            continue
        expanded.extend(found)
    return expanded, errors


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        tolerance = Decimal(args.tolerance)
    except InvalidOperation:
        print(f"billcheck: --tolerance {args.tolerance!r} is not a number",
              file=sys.stderr)
        return 2
    if tolerance < 0:
        print("billcheck: --tolerance cannot be negative", file=sys.stderr)
        return 2

    reports: List[Report] = []
    paths, errors = expand_paths(args.paths)

    for path in paths:
        try:
            invoice = parse_invoice(read_any(path))
        except FileNotFoundError:
            print(f"billcheck: {path}: no such file", file=sys.stderr)
            errors += 1
            continue
        except NoTextLayer as exc:
            print(f"billcheck: {path}: {exc}", file=sys.stderr)
            errors += 1
            continue
        except PdfUnavailable as exc:
            print(f"billcheck: {exc}", file=sys.stderr)
            errors += 1
            continue
        except Exception as exc:                      # noqa: BLE001
            # One unreadable file must not abort a run over a folder of them.
            print(f"billcheck: {path}: could not read ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
            errors += 1
            continue

        if not invoice.source:
            invoice.source = os.path.basename(path)
        report = verify(invoice, tolerance=tolerance)
        reports.append(report)

        if not args.quiet:
            colour = (not args.no_colour) and sys.stdout.isatty()
            print(render_report(report, colour=colour, verbose=args.verbose))
            print()

    if not args.quiet and reports:
        clean = [r for r in reports if not r.failures and not r.warnings]
        bad = [r for r in reports if r.failures]
        review = [r for r in reports if not r.failures and r.warnings]
        parts = [f"{len(reports)} checked"]
        if bad:
            parts.append(f"{len(bad)} with failures")
        if review:
            parts.append(f"{len(review)} to review")
        if clean:
            parts.append(f"{len(clean)} clean")
        print(", ".join(parts) + ".")

    if args.json and reports:
        write_json(reports, args.json)
    if args.csv and reports:
        write_register(reports, args.csv)
    if args.lines and reports:
        write_lines(reports, args.lines)
    if args.review and reports:
        with open(args.review, "w", encoding="utf-8") as handle:
            handle.write(review_sheet(reports))

    if errors:
        return 2
    if any(r.failures for r in reports):
        return 1
    return 0


if __name__ == "__main__":                            # pragma: no cover
    raise SystemExit(main())
