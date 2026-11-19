"""Checks on model output (flag, don't silently fix).

Used in three places:
- before a term is fixed for the document (context terms, learned terms);
- on each model answer, to trigger one retry with precise feedback;
- on the final Arabic of each passage, as issues for the reviewer.
"""
from __future__ import annotations

import re

# Scripts that must never appear in Arabic FS text. Small models (Qwen in
# particular) sometimes switch into Chinese mid-sentence on long inputs.
FOREIGN_SCRIPTS = [
    ("Chinese", re.compile(r"[⺀-⿟　-〿㐀-䶿一-鿿豈-﫿＀-｠]")),
    ("Japanese", re.compile(r"[぀-ヿ]")),
    ("Korean", re.compile(r"[ᄀ-ᇿ㄰-㆏가-힯]")),
    ("Cyrillic", re.compile(r"[Ѐ-ӿ]")),
    ("Thai", re.compile(r"[฀-๿]")),
    ("Hebrew", re.compile(r"[֐-׿]")),
    ("Devanagari", re.compile(r"[ऀ-ॿ]")),
]

# Acronyms that stay in Latin letters in Arabic FS.
LATIN_ALLOWED = {"IFRS", "IFRSS", "IAS", "IASB", "ISA", "ISAS", "IFRIC", "SIC", "IESBA", "IPSAS", "XBRL"}

_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'&.-]*")
_TAG = re.compile(r"</?[a-z]+\d+>")
_PLACEHOLDER = re.compile(r"⟦\s*[ND]\s*\d+\s*⟧")


def foreign_scripts(text: str) -> dict[str, str]:
    """{script name: sample characters} for every non-Arabic script found."""
    found = {}
    for name, rx in FOREIGN_SCRIPTS:
        chars = rx.findall(text or "")
        if chars:
            found[name] = "".join(dict.fromkeys(chars))[:8]
    return found


def latin_words(target: str, source: str = "") -> list[str]:
    """English words left in the Arabic. Allowed: standard acronyms, and upper-case
    acronyms (2-6 letters) that also appear in the source (e.g. a company's initials)."""
    text = _PLACEHOLDER.sub(" ", _TAG.sub(" ", target or ""))
    source_tokens = set(_LATIN_WORD.findall(source or ""))
    out = []
    for word in _LATIN_WORD.findall(text):
        w = word.strip(".-'&")
        if not w:
            continue
        if w.upper() in LATIN_ALLOWED:
            continue
        if w.isupper() and 2 <= len(w.rstrip("s")) <= 6 and (w in source_tokens or w.rstrip("s") in source_tokens):
            continue
        out.append(w)
    return list(dict.fromkeys(out))


def stray_brackets(text: str) -> bool:
    """Placeholder brackets left over after restoring (a mangled placeholder)."""
    return "⟦" in (text or "") or "⟧" in (text or "")


def clean_arabic_term(ar: str) -> bool:
    """A term is only fixed for the document if it is clean Arabic."""
    return not foreign_scripts(ar) and not _LATIN_WORD.search(ar or "") and not stray_brackets(ar)


def output_problems(target: str, source: str) -> list[str]:
    """Problems in an Arabic answer, worded so they work as model feedback and as reviewer flags."""
    problems = []
    for name, sample in foreign_scripts(target).items():
        problems.append(f"contains {name} characters ({sample}); write only Arabic")
    words = latin_words(target, source)
    if words:
        problems.append("English left untranslated: " + ", ".join(words[:6]))
    return problems
