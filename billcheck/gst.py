"""GST identifiers: structure, check digits, and state codes.

A GSTIN is 15 characters and, unusually for an Indian identifier, its last
character is a real check digit computed with a mod-36 variant of Luhn. That
means a mistyped GSTIN can be *proved* wrong rather than guessed at, which is
the difference between a tool that flags things and a tool that is right.

Layout:

    27 AAPFU0939F1 Z V
    ^^ ^^^^^^^^^^ ^ ^ ^
    |  |          | | check character
    |  |          | always Z (reserved by GSTN)
    |  |          entity number for this PAN in this state
    |  PAN of the holder
    state or union-territory code
"""

from __future__ import annotations

import re
from typing import Optional

__all__ = ["gstin_check_character", "gstin_valid", "parse_gstin", "clean_gstin",
           "gstin_state_code",
           "state_name", "state_code_from_name", "pan_valid", "STATE_CODES",
           "STATE_ALIASES", "GSTIN_PATTERN", "validate_gstin"]

#: 38 codes: 28 states, 8 union territories, plus the two used for
#: "other territory" and "centre jurisdiction". Kept here rather than inferred
#: from a list of state names, because the code is what appears on the invoice.
STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu", "26": "Dadra and Nagar Haveli", "27": "Maharashtra",
    "28": "Andhra Pradesh", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh (new)", "38": "Ladakh",
    # 97 is "other territory", 99 is centre jurisdiction.
    "97": "Other Territory", "99": "Centre Jurisdiction",
}

#: Common ways people write a state name, mapped to its code. Used to compare
#: a printed "Place of Supply" against the GSTIN's own state.
STATE_ALIASES = {
    "jammu": "01", "kashmir": "01", "himachal": "02", "punjab": "03",
    "chandigarh": "04", "uttarakhand": "05", "uttaranchal": "05",
    "haryana": "06", "delhi": "07", "new delhi": "07", "rajasthan": "08",
    "uttar pradesh": "09", "up": "09", "bihar": "10", "sikkim": "11",
    "arunachal": "12", "nagaland": "13", "manipur": "14", "mizoram": "15",
    "tripura": "16", "meghalaya": "17", "assam": "18", "west bengal": "19",
    "bengal": "19", "jharkhand": "20", "odisha": "21", "orissa": "21",
    "chhattisgarh": "22", "chattisgarh": "22", "madhya pradesh": "23",
    "mp": "23", "gujarat": "24", "daman": "25", "dadra": "26",
    "maharashtra": "27", "andhra": "28", "andhra pradesh": "28",
    "karnataka": "29", "goa": "30", "lakshadweep": "31", "kerala": "32",
    "tamil nadu": "33", "tamilnadu": "33", "puducherry": "34",
    "pondicherry": "34", "andaman": "35", "telangana": "36", "ladakh": "38",
}

GSTIN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])([0-9]{2}[A-Za-z]{5}[0-9]{4}[A-Za-z][A-Za-z0-9][Zz][A-Za-z0-9])"
    r"(?![A-Za-z0-9])")

_ALPHABET36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PAN_HOLDER_TYPES = frozenset("ABCFGHJLPT")

#: The reserved character at position 14. GSTN defines it as Z; invoices that
#: print something else are rare enough that a mismatch is worth saying out loud.
_RESERVED = "Z"


def _value36(ch: str) -> int:
    return _ALPHABET36.index(ch.upper())


def gstin_check_character(first_fourteen: str) -> str:
    """The fifteenth character, per the GSTN checksum definition.

    Luhn's algorithm over base 36: multiply alternate characters by 2, add the
    digits of the product in base 36, then the check character is whatever makes
    the total a multiple of 36.
    """
    if len(first_fourteen) != 14:
        raise ValueError("need exactly 14 characters")
    total = 0
    for position, char in enumerate(first_fourteen):
        factor = 2 if position % 2 else 1
        product = _value36(char) * factor
        total += product // 36 + product % 36
    return _ALPHABET36[(36 - total % 36) % 36]


#: The fourth character of a PAN says what kind of holder it is. An invoice
#: carrying "ABCDE1234F" has a PAN that cannot exist, whatever its checksum says.
_PAN_HOLDER_TYPES = "PCHFATBLJG"


def clean_gstin(gstin: str) -> str:
    """Uppercase and drop the spaces and hyphens PDFs put inside GSTINs.

    A GSTIN printed across a line break arrives as "27AAPFU 0939F1ZV", and a
    validator that rejects it is blaming the invoice for a layout problem.
    Only alphanumerics survive, so anything else passed in becomes a shorter
    string and fails the length check, which is the right outcome.
    """
    return "".join(ch for ch in (gstin or "") if ch.isalnum()).upper()


def gstin_valid(gstin: str) -> bool:
    """Structure, reserved character and check digit, all three."""
    if not gstin:
        return False
    candidate = clean_gstin(gstin)
    if len(candidate) != 15:
        return False
    if not candidate[:2].isdigit():
        return False
    if candidate[:2] not in STATE_CODES:
        return False
    if not (candidate[2:7].isalpha() and candidate[7:11].isdigit()):
        return False
    if candidate[5] not in _PAN_HOLDER_TYPES:
        return False
    if candidate[13] != _RESERVED:
        return False
    try:
        return gstin_check_character(candidate[:14]) == candidate[14]
    except ValueError:
        return False


def validate_gstin(gstin: str) -> tuple:
    """(ok, reason) — so a failed check can say *why* it failed."""
    if not gstin:
        return False, "no GSTIN on the invoice"
    candidate = clean_gstin(gstin)
    if len(candidate) != 15:
        return False, f"{len(candidate)} characters, a GSTIN has 15"
    if not candidate[:2].isdigit():
        return False, "first two characters are not a state code"
    if candidate[:2] not in STATE_CODES:
        return False, f"state code {candidate[:2]} is not assigned"
    if not candidate[2:7].isalpha():
        return False, "characters 3-7 should be the PAN letters"
    if not candidate[7:11].isdigit():
        return False, "characters 8-11 should be PAN digits"
    if candidate[5] not in _PAN_HOLDER_TYPES:
        return False, (f"PAN character 4 is {candidate[5]}, which is not a PAN "
                       f"holder type ({_PAN_HOLDER_TYPES})")
    if candidate[13] != _RESERVED:
        return False, f"position 14 should be Z, found {candidate[13]}"
    try:
        expected = gstin_check_character(candidate[:14])
    except ValueError:
        return False, "could not compute the check character"
    if expected != candidate[14]:
        return False, f"check character should be {expected}, printed {candidate[14]}"
    return True, f"valid, {state_name(candidate[:2])}"


def gstin_state_code(gstin: str) -> Optional[str]:
    if not gstin or len(gstin.strip()) < 2:
        return None
    code = gstin.strip()[:2]
    return code if code in STATE_CODES else None


def state_name(code: str) -> str:
    return STATE_CODES.get(str(code).strip(), f"unknown code {code}")


def state_code_from_name(name: str) -> Optional[str]:
    """Best-effort: read a printed state name (or a bracketed code) as a code."""
    if not name:
        return None
    text = name.lower().strip()
    bracket = re.search(r"\((\d{2})\)", text)
    if bracket and bracket.group(1) in STATE_CODES:
        return bracket.group(1)
    digits = re.fullmatch(r"\s*(\d{2})\s*", text)
    if digits and digits.group(1) in STATE_CODES:
        return digits.group(1)
    for alias in sorted(STATE_ALIASES, key=len, reverse=True):
        if alias in text:
            return STATE_ALIASES[alias]
    return None


def pan_valid(pan: str) -> bool:
    """Five letters, four digits, one letter, with a holder type CBDT issues."""
    if not pan:
        return False
    candidate = pan.strip().upper()
    if len(candidate) != 10:
        return False
    if not (candidate[:5].isalpha() and candidate[5:9].isdigit()
            and candidate[9].isalpha()):
        return False
    return candidate[3] in _PAN_HOLDER_TYPES


def parse_gstin(gstin: str) -> dict:
    """Break a GSTIN into its parts, for structured output.

    Never raises: an unreadable GSTIN comes back as a dict of empty strings and
    ``{"valid": False}``, because a caller that already has a bad field on a
    real invoice should not also have to catch an exception.
    """
    cleaned = clean_gstin(gstin)
    ok, reason = validate_gstin(cleaned)
    if len(cleaned) != 15:
        return {"raw": cleaned, "valid": False, "reason": reason,
                "state_code": "", "state": "", "pan": "", "entity": "",
                "check": ""}
    state = cleaned[:2]
    return {
        "raw": cleaned,
        "valid": ok,
        "reason": reason,
        "state_code": state,
        "state": state_name(state),
        "pan": cleaned[2:12],
        "entity": cleaned[12],
        "check": cleaned[14],
    }
