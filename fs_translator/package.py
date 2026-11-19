"""Open a .docx (a zip of XML parts), expose the parts as lxml trees, write it back.

Only parts that were requested through `xml()` are re-serialised; every other
zip entry is copied byte for byte, in the original order and with the original
compression, so an untouched document round-trips exactly.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from lxml import etree

# Parts whose text is translated, in reading order.
TEXT_PART_PATTERNS = [
    r"word/document\.xml",
    r"word/header\d*\.xml",
    r"word/footer\d*\.xml",
    r"word/footnotes\.xml",
    r"word/endnotes\.xml",
]

_PARSER = etree.XMLParser(remove_blank_text=False, resolve_entities=False, huge_tree=True)


class DocxPackage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        with zipfile.ZipFile(self.path) as zf:
            self._infos = zf.infolist()
            self._raw = {info.filename: zf.read(info.filename) for info in self._infos}
        self._trees: dict[str, etree._ElementTree] = {}

    # -- access ---------------------------------------------------------------
    def names(self) -> list[str]:
        return [i.filename for i in self._infos]

    def has(self, name: str) -> bool:
        return name in self._raw

    def xml(self, name: str) -> etree._Element:
        """Root element of an XML part (parsed once, then cached and marked dirty)."""
        if name not in self._trees:
            self._trees[name] = etree.ElementTree(etree.fromstring(self._raw[name], _PARSER))
        return self._trees[name].getroot()

    def text_parts(self) -> list[str]:
        names = self.names()
        out = []
        for pattern in TEXT_PART_PATTERNS:
            rx = re.compile(pattern + r"$")
            matched = sorted((n for n in names if rx.match(n)), key=_natural_key)
            out.extend(matched)
        return out

    # -- output ---------------------------------------------------------------
    def save(self, out_path: str | Path) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, "w") as zf:
            for info in self._infos:
                data = self._raw[info.filename]
                if info.filename in self._trees:
                    data = etree.tostring(
                        self._trees[info.filename],
                        xml_declaration=True,
                        encoding="UTF-8",
                        standalone=True,
                    )
                new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                new_info.compress_type = info.compress_type
                new_info.external_attr = info.external_attr
                zf.writestr(new_info, data)
        return out_path


def _natural_key(name: str):
    return [int(tok) if tok.isdigit() else tok for tok in re.split(r"(\d+)", name)]
