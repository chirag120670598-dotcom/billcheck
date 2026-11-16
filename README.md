# billcheck

**Check whether an Indian GST invoice actually adds up.** Offline, free, and in
any script — Devanagari, Gujarati and Tamil digits included.

```console
$ billcheck data/samples/broken_tax_split.pdf
broken_tax_split.pdf  ·  STC/2026-27/0490  ·  71,640.00
  BROKEN — the arithmetic on this invoice is wrong
    FAIL  Tax charged equals the tax the line rates imply
          lines imply 4,428.00 but the invoice charges 4,440.00 — over by 12.00
    FAIL  CGST and SGST are equal, and IGST is not mixed in
          CGST 2,226.00 is not equal to SGST 2,214.00

1 checked, 1 with failures.
```

That invoice is the reason this tool exists. Its printed total is *correct*:

```
67,200.00 + 2,226.00 + 2,214.00 = 71,640.00   ✓ adds up
```

Every checker that reconciles the total passes it. The invoice is still wrong,
because the GST rate on those line items produces 4,428.00 of tax and the bill
charges 4,440.00. The mistake only exists *below* the total, between the line
items and the tax summary. That is the check nobody else does, and it is most of
what this repository is.

---

## Why

Document AI vendors do field extraction: they read the invoice and hand you
numbers. They do not tell you whether the numbers are right, because that is not
a model problem — it is arithmetic. Their pricing is per page because their cost
is per page. Arithmetic has no marginal cost.

|  | Docsumo | Nanonets | billcheck |
|---|---|---|---|
| Price | ~₹25,000/month | ~₹42,000/month | free |
| Cost per page | ₹8–25 | ₹25 | none |
| Runs offline | no | no | **yes** |
| Indic scripts | English only | English only | **yes** |
| Checks line-item arithmetic | not claimed | not claimed | **yes** |
| Source available | no | no | **MIT** |

The comparison is about scope, not quality: those products read scans and
photographs, which this one does not. See [Limits](#limits).

## Install

```bash
pip install billcheck          # pypdf is the only dependency
billcheck invoice.pdf
```

From source:

```bash
git clone https://github.com/billcheck/billcheck
cd billcheck
pip install -e .
```

## Use

```console
$ billcheck *.pdf                     # check a folder
$ billcheck invoice.pdf --verbose     # show the checks that passed too
$ billcheck *.pdf --csv register.csv  # one row per invoice, for Tally or Excel
$ billcheck *.pdf --json out.json --review review.md
```

Exit codes are the contract, so a shell loop or a CI step can rely on them:

| code | meaning |
|---|---|
| 0 | every invoice passed every check |
| 1 | at least one invoice failed a check |
| 2 | the run itself failed (missing file, unreadable PDF, bad flag) |

From Python:

```python
import billcheck

report = billcheck.check("invoice.pdf")
print(report.verdict)              # CLEAN, REVIEW, SUSPECT or BROKEN
for check in report.failures:
    print(check.title, "—", check.detail)
```

## What is checked

Twelve checks. Nine of them are arithmetic.

| # | Check | Catches |
|---|---|---|
| 1 | Supplier GSTIN is valid | a wrong character, a bad state code, a fake PAN |
| 2 | Buyer GSTIN is valid | same, when the bill is B2B |
| 3 | Every line: quantity × rate = taxable | ₹1000 typed instead of ₹54000 |
| 4 | Lines add up to the taxable value | an item missed off the summary |
| 5 | **Tax charged equals the tax the line rates imply** | the case above |
| 6 | CGST = SGST, and IGST is not mixed in | half a correction applied |
| 7 | Place of supply agrees with the tax split | IGST on an intra-state sale |
| 8 | Taxable + tax + round-off = total | a total that does not add up |
| 9 | Amount in words = amount in figures | the cheque-clearing failure |
| 10 | Line items were found | a silent partial read |
| 11 | HSN codes present | a bill that cannot be filed |
| 12 | Invoice number and date present | a bill that cannot be posted |

### When the invoice prints no rate column

Plenty of consolidated bills list the items, then the taxable value, then CGST
and SGST, and leave the rate implied. The most useful check in this tool would
be skipped on every one of those bills, so it solves for the rates instead:

```
WARN  Tax charged equals the tax the line rates imply
      no rate column on this invoice; the rates that fit are 5%, 18%,
      and they reproduce the 8,502.50 of tax exactly. That is an
      inference from the totals, not something the invoice states
```

It searches the seven standard GST rates, and it says `WARN` rather than `PASS`
because the answer is an inference. When more than one combination fits, it says
so instead of choosing one.

### Verdicts

| verdict | meaning |
|---|---|
| `CLEAN` | every check passed |
| `REVIEW` | no failures, but something could not be checked — read it |
| `SUSPECT` | a field cannot be trusted (bad GSTIN, words disagree) |
| `BROKEN` | the money is wrong |

### Tolerance

Comparisons allow ₹1.00 by default, because rounding tax per line and rounding
it once at the end genuinely differ:

```console
$ billcheck invoice.pdf --tolerance 0.01   # see every rounding difference
```

The tolerance is printed in the report, not hidden.

## Reading PDFs

`page.extract_text()` on an invoice returns one column per line, which is
useless: nothing says whether `120` is a quantity or a rate. billcheck reads the
*positions* of the text fragments, groups them into visual rows by their y
coordinate, and sorts each row by x. That rebuilds the table:

```
['1', 'Cotton Fabric 40s', '5208', '120', '450.00', '54000.00', '5']
```

No machine learning, no OCR, no network, no page limit.

## Digits and scripts

`२,४००.००` and `૨૪૦૦` are read as 2400, and labels like
`कुल कर योग्य मूल्य` (taxable value) and `कुल राशि` (total) are understood.
Nine digit blocks, Arabic-Indic and full-width digits, and Hindi/Gujarati month
names all normalise before parsing.

## What ships

```
billcheck/
  money.py     amounts, ₹ words, Indian grouping, digit normalisation
  gst.py       GSTIN checksum (mod-36), 38 state codes, PAN shape
  pdf.py       positional row reconstruction
  parse.py     header, line items, totals
  infer.py     recovering a missing GST rate from the totals
  verify.py    the twelve checks
  export.py    JSON, register CSV, line CSV, review sheet
  cli.py       the command line
```

`pip install -e ".[dev]" && pytest` runs 132 tests, including a regression test
for the bug that read `67200.00` as `672` (see the top of
`tests/test_money.py`; the comment explains why the obvious regex is wrong).

## Limits

Written down because a tool that hides its edges is worse than a small tool that
states them.

- **No OCR.** A scanned or photographed bill has no text layer and is refused
  with `NoTextLayer`, not guessed at. Flatbed scans are out of scope in 0.1.
- **PDF layout is a moving target.** The row reconstruction is general, but a
  new template is a new test case. Eleven samples ship in `data/samples/`, in two
  different house styles, and each one's expected verdict is pinned in
  `tests/test_samples.py`.
- **Not a Tally XML exporter.** The CSV is register-shaped and opens in Tally,
  Excel and Sheets. Tally's XML import format is version-sensitive and is not
  claimed.
- **Arithmetic, not law.** billcheck cannot tell you whether the supply happened,
  whether 12% is the correct rate for those goods, whether the invoice was issued
  in time, or whether e-invoicing was required. It tells you whether the numbers
  on the page agree with each other.
- **English and Hindi labels, Devanagari/Gujarati/Tamil digits.** More label
  sets are a dictionary entry each; more digit coverage is a test case each.

## Licence

MIT.
