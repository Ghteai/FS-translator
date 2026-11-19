"""Clean Word's run noise so a sentence is not split into many tiny runs.

- remove w:proofErr (spell/grammar markers) and w:lastRenderedPageBreak (a layout cache)
- remove rsid* attributes (editing-session ids)
- merge adjacent text-only w:r siblings whose formatting is identical
"""
from __future__ import annotations

from lxml import etree

from .ooxml import W_NS, is_w, local, new_child, set_text, w

_DROP_ELEMENTS = {w("proofErr"), w("lastRenderedPageBreak")}

_RSID_ATTRS = {w(a) for a in (
    "rsidR", "rsidRPr", "rsidRDefault", "rsidP", "rsidDel", "rsidSect", "rsidTr",
)}

# rPr children that do not change how text looks; runs that differ only in these
# are merged (Word often splits runs on language or proofing flags alone).
_IGNORED_FOR_MERGE = {"lang", "noProof"}


def clean_part(root: etree._Element) -> dict:
    stats = {"removed_markers": 0, "removed_rsids": 0, "merged_runs": 0}

    for el in list(root.iter(*_DROP_ELEMENTS)):
        _remove_keep_tail(el)
        stats["removed_markers"] += 1

    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in [a for a in el.attrib if a in _RSID_ATTRS]:
            del el.attrib[attr]
            stats["removed_rsids"] += 1

    stats["literal_tabs"] = _literal_tabs_to_elements(root)

    # Merge runs inside every container that holds runs directly.
    parents = {r.getparent() for r in root.iter(w("r"))}
    for parent in parents:
        stats["merged_runs"] += _merge_runs_in(parent)
    return stats


def _literal_tabs_to_elements(root) -> int:
    """'Name<TAB>Name' typed inside one w:t -> w:t, w:tab, w:t, so the tab separates
    passages like a normal Word tab (some generators write raw tab characters)."""
    count = 0
    for t in list(root.iter(w("t"))):
        if not t.text or "\t" not in t.text:
            continue
        run = t.getparent()
        pieces = t.text.split("\t")
        set_text(t, pieces[0])
        idx = run.index(t)
        for piece in pieces[1:]:
            idx += 1
            new_child(run, "tab", index=idx)
            count += 1
            if piece:
                idx += 1
                set_text(new_child(run, "t", index=idx), piece)
    return count


def _remove_keep_tail(el) -> None:
    parent = el.getparent()
    if parent is None:
        return
    # WordprocessingML has no mixed content, but keep tails safe anyway.
    if el.tail:
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def _merge_runs_in(parent) -> int:
    merged = 0
    prev = None
    prev_key = None
    for child in list(parent):
        if is_w(child, "r") and _is_text_only(child):
            key = format_key(child)
            if prev is not None and key == prev_key:
                _append_text(prev, child)
                parent.remove(child)
                merged += 1
                continue
            prev, prev_key = child, key
        else:
            # Bookmarks and comment ranges are zero-width; merging across them
            # would move them, so any other sibling ends the merge window.
            prev, prev_key = None, None
    return merged


def _is_text_only(run) -> bool:
    has_text = False
    for c in run:
        if not isinstance(c.tag, str):
            continue
        name = local(c)
        if name == "rPr":
            continue
        if name == "t":
            has_text = True
            continue
        return False
    return has_text


def format_key(run) -> bytes:
    """Fingerprint of how a run looks (ignores language/proofing flags)."""
    rpr = run.find(w("rPr"))
    if rpr is None:
        return b""
    clone = etree.fromstring(etree.tostring(rpr))
    for c in list(clone):
        if isinstance(c.tag, str) and etree.QName(c).namespace == W_NS and local(c) in _IGNORED_FOR_MERGE:
            clone.remove(c)
    if len(clone) == 0 and not clone.attrib:
        return b""                       # empty rPr == no rPr
    return etree.tostring(clone, method="c14n")


def _append_text(target, source) -> None:
    t_target = target.findall(w("t"))[-1]
    extra = "".join(t.text or "" for t in source.findall(w("t")))
    set_text(t_target, (t_target.text or "") + extra)
