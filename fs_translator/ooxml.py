"""OOXML helpers: namespaces, element names, and schema-ordered insertion.

Word rejects a file as corrupt when child elements of w:pPr, w:rPr, w:tblPr or
w:sectPr are in the wrong order, so every insertion goes through `ensure_child`,
which places the new element according to the ECMA-376 sequence lists below.
"""
from __future__ import annotations

import re

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"

NSMAP = {"w": W_NS, "m": MATH_NS, "mc": MC_NS}


def w(tag: str) -> str:
    """Clark name for a WordprocessingML element or attribute: w('p') -> '{ns}p'."""
    return f"{{{W_NS}}}{tag}"


def local(el) -> str:
    """Local name of an element ('' for comments / processing instructions)."""
    if not isinstance(el.tag, str):
        return ""
    return etree.QName(el).localname


def is_w(el, name: str) -> bool:
    return isinstance(el.tag, str) and el.tag == w(name)


# --- Schema child orders (ECMA-376 Part 1, transitional) -------------------

PPR_ORDER = [
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl",
    "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens",
    "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN",
    "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing",
    "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment",
    "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange",
]

# Covers both CT_RPr (run properties) and CT_ParaRPr (paragraph-mark properties,
# which start with the revision elements ins/del/moveFrom/moveTo).
RPR_ORDER = [
    "ins", "del", "moveFrom", "moveTo",
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
    "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish",
    "webHidden", "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight",
    "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang",
    "eastAsianLayout", "specVanish", "oMath", "rPrChange",
]

TBLPR_ORDER = [
    "tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
    "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders", "shd",
    "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription", "tblPrChange",
]

SECTPR_ORDER = [
    "headerReference", "footerReference", "footnotePr", "endnotePr", "type", "pgSz",
    "pgMar", "paperSrc", "pgBorders", "lnNumType", "pgNumType", "cols", "formProt",
    "vAlign", "noEndnote", "titlePg", "textDirection", "bidi", "rtlGutter", "docGrid",
    "printerSettings", "sectPrChange",
]

# headerReference and footerReference may interleave, so they share one rank.
_SECTPR_RANK = {name: i for i, name in enumerate(SECTPR_ORDER)}
_SECTPR_RANK["footerReference"] = _SECTPR_RANK["headerReference"]

ORDERS = {
    "pPr": {n: i for i, n in enumerate(PPR_ORDER)},
    "rPr": {n: i for i, n in enumerate(RPR_ORDER)},
    "tblPr": {n: i for i, n in enumerate(TBLPR_ORDER)},
    "sectPr": _SECTPR_RANK,
}

def ensure_child(parent, name: str, order_key: str | None = None):
    """Return the w:<name> child of `parent`, creating it in schema order if missing.

    Unknown children (extension namespaces such as w14:*) are left in place;
    the new element is inserted right after the last known child that must
    precede it, so it never lands behind trailing extension elements.
    """
    existing = parent.find(w(name))
    if existing is not None:
        return existing
    new = new_child(parent, name)
    insert_ordered(parent, new, order_key or local(parent))
    return new


def new_child(parent, name: str, index: int | None = None):
    """Create w:<name> under `parent` so it reuses the document's 'w:' prefix.

    (An element created standalone gets an auto prefix such as 'ns0:'.)
    """
    el = etree.SubElement(parent, w(name))
    if index is not None:
        parent.insert(index, el)
    return el


def insert_ordered(parent, new, order_key: str) -> None:
    rank = ORDERS[order_key]
    my_rank = rank[local(new)]
    insert_at = 0
    for idx, child in enumerate(parent):
        if child is new:
            continue
        if not isinstance(child.tag, str) or etree.QName(child).namespace != W_NS:
            continue
        r = rank.get(local(child))
        if r is not None and r <= my_rank:
            insert_at = idx + 1
    parent.insert(insert_at, new)


def ensure_props(owner, props_name: str):
    """Get or create the properties element (pPr/rPr/tblPr) of a p/r/tbl."""
    existing = owner.find(w(props_name))
    if existing is not None:
        return existing
    return new_child(owner, props_name, index=0)


def set_w_attr(el, name: str, value: str) -> None:
    el.set(w(name), value)


def set_text(t_el, text: str) -> None:
    """Set the text of a w:t, keeping leading/trailing spaces visible to Word."""
    t_el.text = text
    if text and (text[0].isspace() or text[-1].isspace() or "  " in text):
        t_el.set(f"{{{XML_NS}}}space", "preserve")


ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


def has_arabic(text: str | None) -> bool:
    return bool(text) and bool(ARABIC_RE.search(text))


def in_table(p) -> bool:
    """True when paragraph `p` sits in a table cell (not counting text boxes inside cells)."""
    parent = p.getparent()
    while parent is not None:
        if is_w(parent, "tc"):
            return True
        if is_w(parent, "body") or is_w(parent, "txbxContent"):
            return False
        parent = parent.getparent()
    return False
