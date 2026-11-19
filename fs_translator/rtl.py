"""Turn a translated document right-to-left.

- paragraphs: w:bidi (table-cell paragraphs without Arabic, e.g. number columns, are left alone)
- runs containing Arabic: w:rtl, complex-script font, w:lang/@w:bidi, and the
  complex-script twins of bold/italic/size (Word formats Arabic with bCs/iCs/szCs)
- tables: w:bidiVisual (mirrors column order); floating table position mirrored
- frames (w:framePr) and section (w:sectPr/w:bidi) mirrored
- styles.xml: same complex-script mirroring on every style
- numbering.xml: letter lists -> arabicAbjad, Roman -> decimal
All insertions go through `ensure_child`, which keeps schema order.
"""
from __future__ import annotations

from lxml import etree

from .config import CS_FONT
from .ooxml import ensure_child, ensure_props, has_arabic, in_table, is_w, w

BIDI_LANG = "ar-SA"

_MIRROR_PAIRS = (("b", "bCs"), ("i", "iCs"), ("sz", "szCs"))
_SWAP_LR = {"left": "right", "right": "left"}
_NUMFMT_MAP = {
    "lowerLetter": "arabicAbjad",
    "upperLetter": "arabicAbjad",
    "lowerRoman": "decimal",
    "upperRoman": "decimal",
}


def apply_rtl_part(root: etree._Element) -> dict:
    stats = {"paragraphs": 0, "runs": 0, "tables": 0, "frames": 0, "sections": 0}

    for p in root.iter(w("p")):
        texts = _own_texts(p)
        cell = in_table(p)
        if not cell or has_arabic(texts):
            ppr = ensure_props(p, "pPr")
            ensure_child(ppr, "bidi")
            stats["paragraphs"] += 1
            if cell:
                _keep_right_alignment(ppr)
        ppr = p.find(w("pPr"))
        if ppr is not None:
            frame = ppr.find(w("framePr"))
            if frame is not None and _mirror_attr(frame, "xAlign"):
                stats["frames"] += 1

    for r in root.iter(w("r")):
        if has_arabic("".join(t.text or "" for t in r.findall(w("t")))):
            apply_rtl_run(r)
            stats["runs"] += 1

    for tbl in root.iter(w("tbl")):
        tblpr = ensure_props(tbl, "tblPr")
        ensure_child(tblpr, "bidiVisual")
        tblp = tblpr.find(w("tblpPr"))
        if tblp is not None:
            _mirror_attr(tblp, "tblpXSpec")
        stats["tables"] += 1

    for sect in root.iter(w("sectPr")):
        ensure_child(sect, "bidi")
        stats["sections"] += 1
    return stats


def apply_rtl_run(run) -> None:
    rpr = ensure_props(run, "rPr")
    fonts = ensure_child(rpr, "rFonts")
    fonts.set(w("cs"), CS_FONT)
    fonts.attrib.pop(w("cstheme"), None)
    mirror_cs(rpr)
    ensure_child(rpr, "rtl")
    lang = ensure_child(rpr, "lang")
    lang.set(w("bidi"), BIDI_LANG)


def mirror_cs(rpr) -> None:
    """Make bCs/iCs/szCs equal b/i/sz (present with the same value, or absent)."""
    for src_name, dst_name in _MIRROR_PAIRS:
        src = rpr.find(w(src_name))
        dst = rpr.find(w(dst_name))
        if src is None:
            if dst is not None:
                rpr.remove(dst)
            continue
        dst = ensure_child(rpr, dst_name, "rPr")
        dst.attrib.clear()
        dst.attrib.update(src.attrib)


def apply_rtl_styles(root: etree._Element) -> dict:
    stats = {"styles": 0}
    for rpr in root.iter(w("rPr")):
        mirror_cs(rpr)
    for fonts in root.iter(w("rFonts")):
        if fonts.get(w("cs")) is not None or fonts.get(w("cstheme")) is not None:
            fonts.set(w("cs"), CS_FONT)
            fonts.attrib.pop(w("cstheme"), None)

    defaults_rpr = _doc_defaults_rpr(root)
    fonts = ensure_child(defaults_rpr, "rFonts")
    fonts.set(w("cs"), CS_FONT)
    fonts.attrib.pop(w("cstheme"), None)
    lang = ensure_child(defaults_rpr, "lang")
    lang.set(w("bidi"), BIDI_LANG)

    stats["styles"] = len(root.findall(w("style")))
    return stats


def apply_rtl_numbering(root: etree._Element) -> dict:
    stats = {"list_formats_changed": 0}
    for fmt in root.iter(w("numFmt")):
        new = _NUMFMT_MAP.get(fmt.get(w("val")))
        if new:
            fmt.set(w("val"), new)
            stats["list_formats_changed"] += 1
    for rpr in root.iter(w("rPr")):
        mirror_cs(rpr)
    return stats


# --- helpers ------------------------------------------------------------------

def _own_texts(p) -> str:
    """Text of the paragraph itself, excluding paragraphs nested in text boxes."""
    out = []
    for t in p.iter(w("t")):
        anc = t.getparent()
        while anc is not None and not is_w(anc, "p"):
            anc = anc.getparent()
        if anc is p:
            out.append(t.text or "")
    return "".join(out)



def _keep_right_alignment(ppr) -> None:
    """In a bidi paragraph Word swaps jc left/right. A right-aligned cell heading
    (e.g. 'Notes', '2025') must stay right so it lines up with the number cells
    below it, which are not bidi and keep their right alignment."""
    jc = ppr.find(w("jc"))
    if jc is None:
        return
    val = jc.get(w("val"))
    if val == "right":
        jc.set(w("val"), "left")
    elif val == "end":
        jc.set(w("val"), "start")


def _mirror_attr(el, attr: str) -> bool:
    val = el.get(w(attr))
    if val in _SWAP_LR:
        el.set(w(attr), _SWAP_LR[val])
        return True
    return False


def _doc_defaults_rpr(styles_root):
    defaults = styles_root.find(w("docDefaults"))
    if defaults is None:
        defaults = etree.SubElement(styles_root, w("docDefaults"))
        styles_root.insert(0, defaults)
    rpr_default = defaults.find(w("rPrDefault"))
    if rpr_default is None:
        rpr_default = etree.SubElement(defaults, w("rPrDefault"))
        defaults.insert(0, rpr_default)
    rpr = rpr_default.find(w("rPr"))
    if rpr is None:
        rpr = etree.SubElement(rpr_default, w("rPr"))
    return rpr
