"""Money, and the Indian way of writing it.

Everything here exists because invoice arithmetic must never touch a float.
Rs 0.01 lost to binary rounding is the difference between an invoice that
reconciles and one that a CA rejects, and it is invisible until the numbers get
big. All amounts are `Decimal` from the moment they are read.

Two directions are needed and both live here:

* ``parse_amount`` — "+ read "1,23,456.00" as Decimal("123456.00")"
* ``words_to_amount`` — read "Seventy One Thousand Six Hundred Sixty Four Only"
  back into a number, so the printed words can be checked against the printed
  total. Almost no tool does this, and it catches the class of error where the
  digits were edited but the words were not.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

__all__ = ["parse_amount", "is_numeric_cell", "words_to_amount", "format_inr",
           "to_decimal", "quantise", "normalise_digits", "INDIAN_DIGITS"]


class AmountError(ValueError):
    """Raised when a string cannot be read as an amount."""


#: Every Indian script puts its digits at the same offset in its block, exactly
#: as the letters do. An invoice printed in Hindi uses these.
_BLOCKS = (0x0900, 0x0980, 0x0A00, 0x0A80, 0x0B00, 0x0B80, 0x0C00, 0x0C80, 0x0D00)
INDIAN_DIGITS = {}
for _base in _BLOCKS:
    for _i in range(10):
        INDIAN_DIGITS[chr(_base + 0x66 + _i)] = str(_i)
for _i in range(10):
    INDIAN_DIGITS[chr(0x0660 + _i)] = str(_i)          # Arabic-Indic
    INDIAN_DIGITS[chr(0xFF10 + _i)] = str(_i)          # full width

#: Characters that appear around amounts and mean nothing.
_NOISE = re.compile(r"[₹$€£\u00a0\s]|rs\.?|inr", re.IGNORECASE)

#: A number, optionally grouped the Indian way or the Western way.
#:
#: The obvious pattern here is a pair of alternatives, one for grouped numbers
#: (``\d{1,3}(,\d{2,3})*``) and one for plain ones (``\d+``). That pattern is
#: wrong, and expensively so: a regex alternation takes the first branch that
#: matches, and the grouped branch happily matches the first three digits of
#: "67200.00", so an amount of sixty-seven thousand two hundred was read as six
#: hundred and seventy-two. One character class covers both cases correctly.
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

#: A cell that is *only* a number. Used when deciding whether a table cell is a
#: quantity or a description -- "Cotton Fabric 40s" contains digits and must not
#: count as a number.
_STRICT_CELL = re.compile(r"^[-+(]?[\d,]+(?:\.\d+)?[)]?$")


def to_decimal(value) -> Optional[Decimal]:
    """Coerce an int, float, str or Decimal to Decimal, or None.

    A float is routed through ``str`` rather than ``Decimal(float)`` on purpose:
    ``Decimal(0.1)`` is 0.1000000000000000055511151231257827, and that tail is
    how an invoice stops reconciling.
    """
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def normalise_digits(text: str) -> str:
    """Turn Indic digits into ASCII ones so one regex handles every script."""
    return "".join(INDIAN_DIGITS.get(ch, ch) for ch in text or "")


def is_numeric_cell(text: str) -> bool:
    """True only if the whole cell is a number, ignoring currency decoration.

    The distinction matters: ``parse_amount("Cotton Fabric 40s")`` returns 40,
    because a regex looking for a number finds one. That is the right behaviour
    when reading "Taxable Value: 67200.00" and the wrong behaviour when deciding
    which columns of a table are numeric.
    """
    if text is None:
        return False
    cleaned = normalise_digits(str(text)).strip()
    if not cleaned:
        return False
    cleaned = cleaned.replace("/-", "")
    cleaned = _NOISE.sub("", cleaned).replace("%", "")
    if not cleaned:
        return False
    return bool(_STRICT_CELL.match(cleaned))


def parse_amount(text: str) -> Optional[Decimal]:
    """Read an amount out of a messy cell.

    Handles ``1,23,456.00``, ``123456``, ``Rs. 1,23,456/-``, ``(1,234.00)`` for
    negatives, ``-1,234.00``, Indic digits and stray currency symbols.

    Returns ``None`` when the cell does not hold a number at all, which is the
    normal case for a description column. Raises nothing: an invoice parser that
    throws on a stray dash is a parser that fails on real invoices.
    """
    if text is None:
        return None
    cleaned = normalise_digits(str(text)).strip()
    if not cleaned:
        return None

    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        negative = True
        cleaned = cleaned[1:-1]

    # "1,23,456/-" is a common way to write a whole-rupee amount.
    cleaned = cleaned.replace("/-", "").replace("=", "")
    cleaned = _NOISE.sub("", cleaned)

    if cleaned in ("-", "--", "", "."):
        return None

    match = _NUMBER.search(cleaned)
    if not match:
        return None
    raw = match.group(0).replace(",", "")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    if negative:
        value = -value
    return value


def quantise(value: Decimal, places: int = 2) -> Decimal:
    """Round the way an invoice does: half up, to paise."""
    from decimal import ROUND_HALF_UP
    exponent = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# words -> number
# ---------------------------------------------------------------------------

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
#: Indian scale words. Lakh is 10^5 and crore is 10^7 -- there is no "million"
#: on an Indian invoice, and accepting one would hide a real mistake.
_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000,
           "lakhs": 100000, "crore": 10000000, "crores": 10000000}
_SEPARATORS = {"and", "rupees", "rupee", "paise", "paisa", "only", "minus", "-"}


def words_to_amount(text: str) -> Optional[Decimal]:
    """Read an amount written in words, the way a cheque prints it.

        "Seventy One Thousand Six Hundred Sixty Four Only" -> 71664
        "Twelve Lakh Thirty Four Thousand Rupees and Fifty Paise" -> 1234000.50

    Returns ``None`` if the text does not look like an amount in words.
    Returning None rather than raising matters: the words field is often blank
    or truncated, and a missing field is not an error, it is a missing check.
    """
    if not text:
        return None
    tokens = re.findall(r"[A-Za-z]+", text.lower())
    if not tokens:
        return None

    total = Decimal(0)
    current = Decimal(0)
    seen_any = False
    paise_mode = False
    paise = Decimal(0)
    negative = False

    for token in tokens:
        if token == "minus":
            negative = True
            continue
        if token in ("rupee", "rupees", "रुपये", "रुपया", "रुपए"):
            # "Six Hundred Seventy Eight Rupees and Five Paise": the rupee
            # amount ends here. Without this flush, the words after "Rupees"
            # are added to the rupee total and then read as paise, so
            # 12345678 rupees and 5 paise came out as 12345006.83.
            total += current
            current = Decimal(0)
            continue
        if token in ("paise", "paisa", "पैसे", "पैसा"):
            paise_mode = True
            continue
        if token in _SEPARATORS:
            continue
        if token in _UNITS:
            value = _UNITS[token]
            current += value
            seen_any = True
        elif token in _TENS:
            current += _TENS[token]
            seen_any = True
        elif token in _SCALES:
            scale = Decimal(_SCALES[token])
            if scale == 100:
                # "Sixty Four Hundred" is not English; "Six Hundred" is.
                current = (current or 1) * scale
            else:
                total += (current or 1) * scale
                current = Decimal(0)
            seen_any = True
        else:
            # An unknown word means this is prose, not an amount. Better to say
            # "I could not read this" than to invent a number.
            return None

    if not seen_any:
        return None

    if paise_mode:
        paise = current
        current = Decimal(0)
    total = total + current

    result = total + (paise / 100)
    return -result if negative else result


def format_inr(amount, decimals: int = 2) -> str:
    """Render an amount with Indian grouping. For reports, never for arithmetic."""
    value = to_decimal(amount)
    if value is None:
        return ""
    negative = value < 0
    value = abs(quantise(value, decimals))
    whole, _, fraction = f"{value:.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    out = f"{whole}.{fraction}" if decimals else whole
    return f"-{out}" if negative else out
