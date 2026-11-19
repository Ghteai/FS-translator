"""Lock numbers and dates before the model sees a passage; restore them after.

    "Profit for 2025 was AED 1,234 million (2024: 1,100) as at 31 December 2025"
 -> "Profit for ⟦N1⟧ was AED ⟦N2⟧ million (⟦N3⟧: ⟦N4⟧) as at ⟦D1⟧"

The model can move placeholders but never change a figure. Dates are restored in
Arabic form (31 ديسمبر 2025) from a fixed month table, numbers are restored
exactly as written (Western digits). Tags such as <b1> are never touched.

Every placeholder must come back exactly once; anything else is reported as an
issue and nothing is silently fixed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TAG_SPLIT = re.compile(r"(</?[a-z]+\d+>)")
LRM = "\u200e"   # invisible left-to-right mark

MONTHS_AR = {
    "january": "يناير", "february": "فبراير", "march": "مارس", "april": "أبريل",
    "may": "مايو", "june": "يونيو", "july": "يوليو", "august": "أغسطس",
    "september": "سبتمبر", "october": "أكتوبر", "november": "نوفمبر", "december": "ديسمبر",
}
_MONTH_ALIASES = {m[:3]: m for m in MONTHS_AR} | {"sept": "september"} | {m: m for m in MONTHS_AR}
_MONTH_RE = (r"(?P<{name}>January|February|March|April|May|June|July|August|September|October|"
             r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?")

# Abjad letters for note sub-references: note 12(a) -> 12(أ), matching the
# letter lists that rtl.py switches to arabicAbjad.
ABJAD = "أبجدهوزحطيكلمنسعفصقرشتثخذضظغ"

_NOT_WORD_BEFORE = r"(?<![A-Za-z0-9.,])"
_NOT_WORD_AFTER = r"(?![A-Za-z0-9])"

_DATE_PATTERNS = [
    # 31 December 2025 / 31 Dec. 2025 / 31 December
    re.compile(_NOT_WORD_BEFORE + r"(?P<day>\d{1,2})\s+" + _MONTH_RE.format(name="month")
               + r"(?:,?\s+(?P<year>\d{4}))?" + _NOT_WORD_AFTER, re.I),
    # December 31, 2025 (year required: "may 5" is too ambiguous without it)
    re.compile(r"(?<![A-Za-z])" + _MONTH_RE.format(name="month") + r"\s+(?P<day>\d{1,2})"
               r",?\s+(?P<year>\d{4})" + _NOT_WORD_AFTER, re.I),
    # December 2025
    re.compile(r"(?<![A-Za-z])" + _MONTH_RE.format(name="month") + r",?\s+(?P<year>\d{4})" + _NOT_WORD_AFTER, re.I),
]

_NUMBER_RE = re.compile(
    _NOT_WORD_BEFORE + r"(?:"
    r"\d{1,2}/\d{1,2}/\d{2,4}"                                   # 31/12/2025
    r"|\d{4}-\d{2}-\d{2}"                                        # 2025-12-31
    r"|\d+(?:-\d+)+"                                             # 000000-1, 2024-2025
    r"|\((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)"                # (12,500) negative amount
    r"|[-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?"              # 1,234.5 / -5 / 12.5%
    r")" + _NOT_WORD_AFTER
)

# Note sub-reference right after a number: 12(a), 4(b)(ii) is left alone after (b).
_SUBREF_RE = re.compile(r"^\(([a-z])\)")

_PLACEHOLDER_RE = re.compile(r"⟦\s*([ND])\s*(\d+)\s*⟧")


@dataclass
class Locked:
    text: str                                      # what the model sees
    values: dict[str, str] = field(default_factory=dict)   # ⟦N1⟧ -> source text
    arabic: dict[str, str] = field(default_factory=dict)   # ⟦D1⟧ -> Arabic rendering

    @property
    def needs_model(self) -> bool:
        """False when nothing but placeholders, tags and punctuation is left."""
        rest = _PLACEHOLDER_RE.sub("", TAG_SPLIT.sub("", self.text))
        return bool(re.search(r"[^\W\d_]", rest))


def lock(text: str) -> Locked:
    locked = Locked(text="")
    counters = {"N": 0, "D": 0}

    def add(kind: str, source: str, arabic: str) -> str:
        counters[kind] += 1
        key = f"⟦{kind}{counters[kind]}⟧"
        locked.values[key] = source
        locked.arabic[key] = arabic
        return key

    out = []
    for i, piece in enumerate(TAG_SPLIT.split(text)):
        if i % 2 == 1:                     # a formatting tag
            out.append(piece)
            continue
        out.append(_lock_piece(piece, add))
    locked.text = "".join(out)
    return locked


def _lock_piece(piece: str, add) -> str:
    # Dates first (they contain numbers), then the remaining numbers.
    def date(m: re.Match) -> str:
        # "5 may" / "march 3" in lower case without a year are words, not dates.
        if m.group("month").islower() and not m.group("year"):
            return m.group(0)
        return add("D", m.group(0), _date_ar(m))

    for pattern in _DATE_PATTERNS:
        piece = pattern.sub(date, piece)

    out, pos = [], 0
    for m in _NUMBER_RE.finditer(piece):
        if _inside_placeholder(piece, m.start()):
            continue
        start, end = m.start(), m.end()
        value = m.group(0)
        # In Arabic text the bidi algorithm treats digits as "Arabic numbers", and a
        # hyphen between them does not join them: 000000-1 shows as 1-000000 and -5
        # as 5-. A left-to-right mark in front keeps the number in its written order.
        arabic = LRM + value if ("-" in value or "−" in value) else value
        sub = _SUBREF_RE.match(piece[end:])
        if sub and value.isdigit():
            letter = sub.group(1)
            value += sub.group(0)
            arabic += f"({ABJAD[ord(letter) - ord('a')]})"
            end += len(sub.group(0))
        out.append(piece[pos:start])
        out.append(add("N", value, arabic))
        pos = end
    out.append(piece[pos:])
    return "".join(out)


def _inside_placeholder(text: str, idx: int) -> bool:
    opened = text.rfind("⟦", 0, idx)
    return opened != -1 and text.find("⟧", opened) >= idx


def _date_ar(m: re.Match) -> str:
    month = _MONTH_ALIASES[m.group("month").lower().rstrip(".")]
    parts = []
    day = m.groupdict().get("day")
    if day:
        parts.append(str(int(day)))
    parts.append(MONTHS_AR[month])
    if m.group("year"):
        parts.append(m.group("year"))
    return " ".join(parts)


def restore(translated: str, locked: Locked, *, arabic: bool = True) -> tuple[str, list[str]]:
    """Put locked values back. Returns (text, issues)."""
    issues: list[str] = []
    seen: dict[str, int] = {}

    def put_back(m: re.Match) -> str:
        key = f"⟦{m.group(1)}{m.group(2)}⟧"
        if key not in locked.values:
            issues.append(f"unknown placeholder {key} in translation")
            return m.group(0)
        seen[key] = seen.get(key, 0) + 1
        return (locked.arabic if arabic else locked.values)[key]

    text = _PLACEHOLDER_RE.sub(put_back, translated)
    for key, source in locked.values.items():
        n = seen.get(key, 0)
        if n == 0:
            issues.append(f"missing {'date' if key.startswith('⟦D') else 'number'} '{source}'")
        elif n > 1:
            issues.append(f"'{source}' appears {n} times (once in source)")
    return text, issues
