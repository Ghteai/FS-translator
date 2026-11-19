"""Write a (tagged) translation back into the runs of its passage.

Rules:
- tags valid and in the same order as the source -> fill the original runs in
  place (hyperlinks, bookmarks and fields around them stay untouched); text that
  falls where the source had no plain run gets a new run with the base formatting.
- tags valid but reordered -> rebuild the passage as new runs (one per chunk,
  cloned formatting) at the position of the first run, and flag it.
- tags broken -> drop tags, put all text in the first run, and flag it.
"""
from __future__ import annotations

import copy
import re

from .ooxml import new_child, set_text, w
from .segment import Passage, Slot

TAG_RE = re.compile(r"<(/?)([a-z]+\d+)>")


class TagError(ValueError):
    pass


def parse_tagged(text: str, expected_tags: list[str]) -> list[tuple[str | None, str]]:
    """Split ``a <b1>b</b1> c`` into [(None,'a '), ('b1','b'), (None,' c')]."""
    chunks: list[tuple[str | None, str]] = []
    open_tag: str | None = None
    seen: list[str] = []
    pos = 0
    for m in TAG_RE.finditer(text):
        chunk = text[pos:m.start()]
        closing, name = m.group(1) == "/", m.group(2)
        if not closing:
            if open_tag is not None:
                raise TagError(f"tag <{name}> opened inside <{open_tag}>")
            if name in seen:
                raise TagError(f"tag <{name}> used twice")
            if chunk:
                chunks.append((None, chunk))
            open_tag = name
            seen.append(name)
        else:
            if open_tag != name:
                raise TagError(f"unexpected </{name}>")
            chunks.append((name, chunk))
            open_tag = None
        pos = m.end()
    if open_tag is not None:
        raise TagError(f"tag <{open_tag}> not closed")
    if text[pos:]:
        chunks.append((None, text[pos:]))
    if sorted(seen) != sorted(expected_tags):
        missing = sorted(set(expected_tags) - set(seen))
        extra = sorted(set(seen) - set(expected_tags))
        raise TagError(f"tags differ from source (missing {missing}, extra {extra})")
    return chunks


def strip_tags(text: str) -> str:
    return TAG_RE.sub("", text)


def apply_translation(passage: Passage, translated: str) -> list[str]:
    """Write `translated` into the passage's runs. Returns a list of issues."""
    issues: list[str] = []
    try:
        chunks = parse_tagged(translated, passage.tags)
    except TagError as exc:
        issues.append(f"formatting tags: {exc}; formatting inside the sentence was dropped")
        _fill_slot(passage.slots[0], passage.lead + strip_tags(translated).strip() + passage.trail)
        for s in passage.slots[1:]:
            _fill_slot(s, "")
        return issues

    if not chunks:
        chunks = [(None, "")]
    first_tag, last_tag = chunks[0][0], chunks[-1][0]
    chunks[0] = (first_tag, passage.lead + chunks[0][1])
    chunks[-1] = (last_tag, chunks[-1][1] + passage.trail)

    if [c[0] for c in chunks if c[0]] == passage.tags:
        _fill_in_order(passage, chunks)
    else:
        issues.append("formatting tags were reordered; runs rebuilt (check hyperlinks/bookmarks)")
        _rebuild(passage, chunks)
    return issues


# --- strategies ------------------------------------------------------------------

def _fill_in_order(passage: Passage, chunks) -> None:
    # Gaps: untagged text before tag 0, between tags, and after the last tag.
    gaps: list[str] = [""]
    tagged: dict[str, str] = {}
    for tag, text in chunks:
        if tag is None:
            gaps[-1] += text
        else:
            tagged[tag] = text
            gaps.append("")

    # Source layout in the same shape: for each gap, the base slot there (or None).
    src_gaps: list[Slot | None] = [None]
    tag_slots: list[Slot] = []
    for s in passage.slots:
        if s.tag is None:
            src_gaps[-1] = s
        else:
            tag_slots.append(s)
            src_gaps.append(None)

    base_rpr = passage.base_rpr
    for k, text in enumerate(gaps):
        slot = src_gaps[k]
        if slot is not None:
            _fill_slot(slot, text)
        elif text:
            if k == 0:
                anchor = tag_slots[0].units[0].run
                _insert_run(anchor, base_rpr, text, before=True)
            else:
                anchor = tag_slots[k - 1].units[-1].run
                _insert_run(anchor, base_rpr, text, before=False)
    for s in tag_slots:
        _fill_slot(s, tagged[s.tag])


def _rebuild(passage: Passage, chunks) -> None:
    rpr_by_tag = {s.tag: s.units[0].run.find(w("rPr")) for s in passage.slots if s.tag}
    base_rpr = passage.base_rpr
    anchor = passage.slots[0].units[0].run
    for tag, text in chunks:
        if text:
            _insert_run(anchor, rpr_by_tag.get(tag) if tag else base_rpr, text, before=True)
    for s in passage.slots:
        _fill_slot(s, "")


# --- primitives --------------------------------------------------------------------

def _fill_slot(slot: Slot, text: str) -> None:
    set_text(slot.units[0].t, text)
    for u in slot.units[1:]:
        set_text(u.t, "")


def _insert_run(anchor_run, rpr, text: str, before: bool) -> None:
    parent = anchor_run.getparent()
    idx = parent.index(anchor_run)
    run = new_child(parent, "r", index=idx if before else idx + 1)
    if rpr is not None:
        run.append(copy.deepcopy(rpr))
    t = new_child(run, "t")
    set_text(t, text)
