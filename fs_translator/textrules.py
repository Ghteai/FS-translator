"""Rules about which text needs translating.

Step 1 version: a passage is skipped when, after removing numbers, punctuation,
dashes, brackets and currency/unit codes, no letters are left. Step 2 adds
number/date placeholders on top of this.
"""
from __future__ import annotations

import re

CURRENCY_CODES = {
    "AED", "SAR", "QAR", "KWD", "BHD", "OMR", "EGP", "JOD", "USD", "EUR", "GBP",
    "CHF", "JPY", "CNY", "INR", "US$", "$", "€", "£",
}

# Unit suffixes that appear in amount columns: AED'000, AED 000, USD'm, '000s.
_UNIT_RE = re.compile(r"(?i)^[’'`]?(000s?|000|m|mn|bn|k)$")
_TOKEN_RE = re.compile(r"[A-Za-z$€£]+[A-Za-z$€£.]*|[’'`]\w+")
_LETTER_RE = re.compile(r"[^\W\d_]")


def is_translatable(text: str) -> bool:
    if not text or not text.strip():
        return False
    if not _LETTER_RE.search(text):
        return False                      # only digits, dashes, brackets, punctuation
    remaining = _TOKEN_RE.sub(lambda m: "" if _is_code(m.group(0)) else m.group(0), text)
    return bool(_LETTER_RE.search(remaining))


def _is_code(token: str) -> bool:
    tok = token.strip(".")
    return tok.upper() in CURRENCY_CODES or bool(_UNIT_RE.match(tok))
