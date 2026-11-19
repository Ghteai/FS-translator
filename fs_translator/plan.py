"""Decide which parts of a locked passage the model translates and which parts code keeps.

Two structures are handled in code because small models lose them:

1. Section numbering at the start: "⟦N1⟧. Material accounting policies"
   (source "3. Material accounting policies"). The number prefix is kept as is
   and only the heading text goes to the model.

2. A formatted run-in heading: "<b1>Inventories</b1> – Inventories are measured..."
   The heading and the sentence are translated separately and the tags are put
   back by code, so the model never has to carry them. The heading then also
   shares its cached Arabic with the same label elsewhere in the document.

Everything else is one piece translated as a whole.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .placeholders import Locked

MAX_HEADING_WORDS = 10

_TAG_OPEN = re.compile(r"<([a-z]+\d+)>")
_PLACEHOLDER = re.compile(r"⟦[ND]\d+⟧")
_NUM_PREFIX = re.compile(r"^(⟦N\d+⟧)([.)]?)(\s+)(\S.*)$", re.S)
# <b1>Heading</b1> – rest   |   <b1>Heading</b1>: rest
_HEADING_SEP = re.compile(r"^<([a-z]+\d+)>([^<]+?)</\1>(\s*[–—:-]\s*)(\S.*)$", re.S)
# <b1>Heading:</b1> rest    |   <b1>Heading.</b1> rest
_HEADING_PUNCT = re.compile(r"^<([a-z]+\d+)>([^<]+?[:.])</\1>(\s+)(\S.*)$", re.S)
# Section numbers look like 3 or 4.1 or 12.3.2, never like 2025 or 1,234.
_SECTION_NUMBER = re.compile(r"^\d{1,2}(\.\d{1,2}){0,3}$")


@dataclass
class Piece:
    text: str
    translate: bool            # False: copied into the Arabic exactly as is


def plan(locked: Locked) -> list[Piece]:
    pieces: list[Piece] = []
    text = locked.text

    m = _NUM_PREFIX.match(text)
    if m and _has_letters(m.group(4)):
        value = locked.values.get(m.group(1), "")
        if _SECTION_NUMBER.match(value) and (m.group(2) or "." in value):
            pieces.append(Piece(m.group(1) + m.group(2) + m.group(3), False))
            text = m.group(4)

    h = _HEADING_SEP.match(text) or _HEADING_PUNCT.match(text)
    if h and _has_letters(h.group(2)) and _has_letters(h.group(4)) and len(h.group(2).split()) <= MAX_HEADING_WORDS:
        tag = h.group(1)
        pieces += [
            Piece(f"<{tag}>", False),
            Piece(h.group(2).strip(), True),
            Piece(f"</{tag}>{h.group(3)}", False),
            Piece(h.group(4), True),
        ]
    else:
        pieces.append(Piece(text, True))
    return pieces


def sub_locked(locked: Locked, text: str) -> Locked:
    """The Locked view of one piece: only the placeholders that occur in it."""
    keys = set(_PLACEHOLDER.findall(text))
    return Locked(
        text=text,
        values={k: v for k, v in locked.values.items() if k in keys},
        arabic={k: v for k, v in locked.arabic.items() if k in keys},
    )


def tags_in(text: str) -> list[str]:
    return _TAG_OPEN.findall(text)


def _has_letters(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", _PLACEHOLDER.sub("", re.sub(r"</?[a-z]+\d+>", "", text))))
