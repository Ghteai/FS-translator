"""Fake translators for testing layout and RTL without a model."""
from __future__ import annotations

import re

_PROTECTED = re.compile(r"(</?[a-z]+\d+>|⟦[^⟧]*⟧)")

_LETTERS = {
    "a": "ا", "b": "ب", "c": "ك", "d": "د", "e": "ي", "f": "ف", "g": "ج", "h": "ه",
    "i": "ي", "j": "ج", "k": "ك", "l": "ل", "m": "م", "n": "ن", "o": "و", "p": "ب",
    "q": "ق", "r": "ر", "s": "س", "t": "ت", "u": "و", "v": "ف", "w": "و", "x": "كس",
    "y": "ي", "z": "ز",
}


class PseudoArabicTranslator:
    """Replaces each Latin letter with an Arabic letter; keeps digits, tags, placeholders.

    Produces real Arabic script of about the same length, so RTL settings,
    fonts and layout can be checked in Word before any model is involved.
    """
    name = "pseudo-arabic"

    def translate(self, text: str, context: dict) -> str:
        parts = _PROTECTED.split(text)
        out = []
        for i, part in enumerate(parts):
            if i % 2 == 1:                 # tag or placeholder: keep exactly
                out.append(part)
            else:
                out.append("".join(_LETTERS.get(ch.lower(), ch) for ch in part))
        return "".join(out)


class IdentityTranslator:
    """Returns the text unchanged (round trip through the full write-back path)."""
    name = "identity"
    target_arabic = False          # restore dates in their English form

    def translate(self, text: str, context: dict) -> str:
        return text
