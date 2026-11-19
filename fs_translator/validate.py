"""Check schema child order in pPr / rPr / tblPr / sectPr before saving.

Word calls a file corrupt when these are out of order; this catches it in tests
and in the pipeline report instead of in front of a reviewer.
"""
from __future__ import annotations

from lxml import etree

from .ooxml import ORDERS, W_NS, local, w

_CHECKED = {w(name): name for name in ORDERS}


def order_problems(root: etree._Element, part: str = "") -> list[str]:
    problems = []
    for el in root.iter(*_CHECKED):
        rank = ORDERS[_CHECKED[el.tag]]
        last_rank, last_name = -1, None
        for child in el:
            if not isinstance(child.tag, str) or etree.QName(child).namespace != W_NS:
                continue
            name = local(child)
            r = rank.get(name)
            if r is None:
                continue
            if r < last_rank:
                problems.append(f"{part}: <w:{name}> after <w:{last_name}> in <w:{local(el)}>")
            last_rank, last_name = r, name
        names = [local(c) for c in el if isinstance(c.tag, str)]
        dupes = {n for n in names if names.count(n) > 1 and n not in ("headerReference", "footerReference")}
        for n in sorted(dupes):
            problems.append(f"{part}: <w:{n}> repeated in <w:{local(el)}>")
    return problems
