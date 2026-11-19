"""Term consistency within one document.

Two sources of fixed terms:
1. key terms from the context pass (fixed before translation starts);
2. short labels learned during translation: the first time a heading or table
   label (a few words, no numbers) is translated cleanly, its Arabic becomes the
   fixed term for that phrase in the rest of the document.

For each passage, only the fixed terms that occur in it are put in the prompt
(longest first, so "Total current assets" wins over "current assets").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .checks import clean_arabic_term
from .ooxml import has_arabic

MAX_LEARN_WORDS = 6
MAX_TERMS_PER_PROMPT = 15


@dataclass
class Term:
    en: str
    ar: str
    origin: str            # "glossary" | "context" | "learned"
    pattern: re.Pattern = field(repr=False, default=None)
    used: int = 0          # passages whose prompt included this term


class TermTable:
    def __init__(self):
        self._terms: dict[str, Term] = {}

    def __len__(self) -> int:
        return len(self._terms)

    def all(self) -> list[Term]:
        return list(self._terms.values())

    def relevant(self) -> list[Term]:
        """Terms worth showing: everything from this document, glossary terms only if used."""
        return [t for t in self._terms.values() if t.origin != "glossary" or t.used]

    def add(self, en: str, ar: str, origin: str) -> bool:
        """Add a term unless that English phrase is already fixed (first one wins)."""
        en = _norm(en)
        if not en or not has_arabic(ar) or not clean_arabic_term(ar) or en.lower() in self._terms:
            return False
        pattern = re.compile(r"(?<![A-Za-z])" + re.escape(en) + r"(?![A-Za-z])", re.I)
        self._terms[en.lower()] = Term(en, ar.strip(), origin, pattern)
        return True

    def learn(self, source_plain: str, target_plain: str) -> bool:
        """Store a short label's first clean translation."""
        src = _norm(source_plain)
        words = src.split()
        if not (1 <= len(words) <= MAX_LEARN_WORDS):
            return False
        if re.search(r"[\d⟦<]", src) or re.search(r"[A-Za-z⟦<]", target_plain):
            return False
        return self.add(src.rstrip(".:"), target_plain.strip().rstrip(".:"), "learned")

    def find(self, text: str, limit: int = MAX_TERMS_PER_PROMPT, count: bool = True) -> list[Term]:
        """Fixed terms occurring in `text`, longest first, without overlaps."""
        covered: list[tuple[int, int]] = []      # every span claimed by a longer term
        first: dict[str, tuple[int, Term]] = {}  # term -> position of its first free match
        for term in sorted(self._terms.values(), key=lambda t: -len(t.en)):
            for m in term.pattern.finditer(text):
                if any(s < m.end() and m.start() < e for s, e in covered):
                    continue
                # Claim all occurrences, so "Board of directors" also hides "Directors"
                # inside its later repetitions, not only the first one.
                covered.append((m.start(), m.end()))
                first.setdefault(term.en.lower(), (m.start(), term))
        found = [t for _, t in sorted(first.values(), key=lambda x: x[0])][:limit]
        if count:
            for t in found:
                t.used += 1
        return found


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()
