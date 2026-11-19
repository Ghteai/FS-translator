"""Split a Word part into translatable passages.

A passage is a stretch of text inside one paragraph, cut at tabs, breaks, field
characters, symbols, footnote/endnote references and embedded objects. Text in
deletions, field instructions and simple fields is never collected.

Each passage keeps references to its w:t elements ("units") so the translation
can be written back into the same runs. When a passage mixes formatting, the
non-dominant runs are wrapped in tags (``Profit for the <b1>year</b1>``) so the
model can keep formatting inside the sentence.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

from .clean import format_key
from .ooxml import W_NS, in_table, local, w
from .textrules import is_translatable

# Containers whose runs are part of the paragraph flow: descend into them.
_TRANSPARENT = {"hyperlink", "ins", "moveTo", "smartTag", "customXml", "dir", "bdo"}
# Zero-width markers: ignore without ending the passage.
_MARKERS = {
    "pPr", "bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd",
    "moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd",
    "permStart", "permEnd", "proofErr",
}
# Hidden/removed content: skip without ending the passage.
_SKIP_SILENT = {"del", "moveFrom"}
# Inside a run, these do not end the passage.
_RUN_IGNORED = {"rPr", "lastRenderedPageBreak", "delText"}


@dataclass
class Unit:
    t: etree._Element          # the w:t element
    run: etree._Element        # its w:r
    key: bytes                 # formatting fingerprint of the run

    @property
    def text(self) -> str:
        return self.t.text or ""


@dataclass
class Slot:
    tag: str | None            # None = dominant ("base") formatting
    units: list[Unit]

    @property
    def text(self) -> str:
        return "".join(u.text for u in self.units)


@dataclass
class Passage:
    id: str
    part: str
    paragraph: etree._Element
    slots: list[Slot]
    source: str                # tagged, whitespace-trimmed text sent to the model
    lead: str = ""             # whitespace trimmed from the start
    trail: str = ""            # whitespace trimmed from the end
    in_table: bool = False
    translatable: bool = True
    locked: str | None = None                       # source with ⟦N1⟧/⟦D1⟧ placeholders
    placeholders: dict[str, str] = field(default_factory=dict)
    terms: list[dict] = field(default_factory=list)  # fixed terms given to the model
    target: str | None = None
    issues: list[str] = field(default_factory=list)

    @property
    def units(self) -> list[Unit]:
        return [u for s in self.slots for u in s.units]

    @property
    def tags(self) -> list[str]:
        return [s.tag for s in self.slots if s.tag]

    @property
    def base_rpr(self):
        for s in self.slots:
            if s.tag is None:
                rpr = s.units[0].run.find(w("rPr"))
                return rpr
        return self.slots[0].units[0].run.find(w("rPr"))


def extract_passages(root: etree._Element, part: str) -> list[Passage]:
    passages: list[Passage] = []
    for p in root.iter(w("p")):
        cell = in_table(p)
        groups: list[list[Unit]] = [[]]
        _walk(p, groups)
        for units in groups:
            if not any(u.text.strip() for u in units):
                continue
            passage = _build_passage(units, part, f"{part}#{len(passages) + 1}", p, cell)
            passages.append(passage)
    return passages


# --- walking -------------------------------------------------------------------

def _walk(container, groups: list[list[Unit]]) -> None:
    for child in container:
        if not isinstance(child.tag, str):
            continue
        if etree.QName(child).namespace != W_NS:
            _break(groups)               # math, extension content, ...
            continue
        name = local(child)
        if name == "r":
            _walk_run(child, groups)
        elif name in _TRANSPARENT:
            _walk(child, groups)
        elif name == "sdt":
            content = child.find(w("sdtContent"))
            if content is not None:
                _walk(content, groups)
        elif name in _MARKERS or name in _SKIP_SILENT:
            continue
        else:                            # fldSimple, oMath, unknown: boundary, not translated
            _break(groups)


def _walk_run(run, groups: list[list[Unit]]) -> None:
    key = None
    for c in run:
        if not isinstance(c.tag, str):
            continue
        name = local(c)
        if name in _RUN_IGNORED:
            continue
        if name == "t":
            if key is None:
                key = _format_key(run)
            groups[-1].append(Unit(c, run, key))
        else:                            # tab, br, cr, fldChar, sym, references, drawings...
            _break(groups)


def _break(groups: list[list[Unit]]) -> None:
    if groups[-1]:
        groups.append([])



_LINK = b"link:"


def _format_key(run) -> bytes:
    key = format_key(run)
    parent = run.getparent()
    if parent is not None and local(parent) == "hyperlink":
        # Each hyperlink is its own span even if styled like the text around it.
        pos = parent.getparent().index(parent) if parent.getparent() is not None else 0
        key = _LINK + str(pos).encode() + b":" + key
    return key


# --- tagging -------------------------------------------------------------------

def _build_passage(units: list[Unit], part: str, pid: str, p, in_table: bool) -> Passage:
    # Dominant formatting = the one covering the most non-space characters.
    # Hyperlink text is never the base (unless the whole passage is a link), so
    # the link stays a separate tagged span and keeps its w:hyperlink wrapper.
    weight: dict[bytes, int] = {}
    for u in units:
        if not u.key.startswith(_LINK):
            weight[u.key] = weight.get(u.key, 0) + len(u.text.strip())
    if not weight:
        weight = {u.key: len(u.text.strip()) for u in units}
    base_key = max(weight, key=lambda k: weight[k])

    slots: list[Slot] = []
    counters: dict[str, int] = {}
    prev_key = None
    for u in units:
        # A whitespace-only run's formatting is invisible; fold it into base text.
        is_base = u.key == base_key or not u.text.strip()
        key = base_key if is_base else u.key
        if slots and key == prev_key:
            slots[-1].units.append(u)
            continue
        tag = None
        if not is_base:
            kind = _tag_kind(u.run, units, base_key)
            counters[kind] = counters.get(kind, 0) + 1
            tag = f"{kind}{counters[kind]}"
        slots.append(Slot(tag, [u]))
        prev_key = key

    pieces = []
    for s in slots:
        text = s.text
        if s.tag is None:
            pieces.append(text)
        else:
            core = text.strip()
            lead_ws = text[: len(text) - len(text.lstrip())]
            trail_ws = text[len(text.rstrip()):]
            pieces.append(f"{lead_ws}<{s.tag}>{core}</{s.tag}>{trail_ws}")
    full = "".join(pieces)
    stripped = full.strip()
    lead = full[: len(full) - len(full.lstrip())]
    trail = full[len(full.rstrip()):]

    plain = "".join(s.text for s in slots)
    return Passage(
        id=pid, part=part, paragraph=p, slots=slots, source=stripped,
        lead=lead, trail=trail, in_table=in_table, translatable=is_translatable(plain),
    )


def _tag_kind(run, units: list[Unit], base_key: bytes) -> str:
    """Short tag name hinting what differs: a (link), b(old), i(talic), u(nderline), s(uper/sub), f(ormat)."""
    if local(run.getparent()) == "hyperlink":
        return "a"
    rpr = run.find(w("rPr"))
    base_run = next((u.run for u in units if u.key == base_key), None)
    base_rpr = base_run.find(w("rPr")) if base_run is not None else None

    def on(props, name):
        if props is None:
            return False
        el = props.find(w(name))
        if el is None:
            return False
        return el.get(w("val"), "true") not in ("0", "false", "none")

    for name, kind in (("b", "b"), ("i", "i"), ("u", "u"), ("vertAlign", "s")):
        if on(rpr, name) != on(base_rpr, name):
            return kind
    return "f"
