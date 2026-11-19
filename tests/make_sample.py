"""Build a small but realistic FS .docx for tests (hand-written OOXML, no dependencies).

It deliberately contains the things that break naive translators: runs split by
proofErr and rsids, bold inside a sentence, a footnote reference, a lettered
list, a hyperlink, a header frame aligned right, a PAGE field, a statement table
with notes, amounts, brackets and dashes.

    python tests/make_sample.py samples/sample_fs.docx
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
W14 = 'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"'
MC = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'

CONTENT_TYPES = DECL + """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>
<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
</Types>"""

ROOT_RELS = DECL + """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOC_RELS = DECL + """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>
<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
<Relationship Id="rId6" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://www.ifrs.org" TargetMode="External"/>
</Relationships>"""

STYLES = DECL + f"""<w:styles {W}>
<w:docDefaults>
  <w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cstheme="minorBidi"/><w:sz w:val="20"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault>
  <w:pPrDefault><w:pPr><w:spacing w:after="120"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="240"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:caps/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="FootnoteReference"><w:name w:val="footnote reference"/><w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="FootnoteText"><w:name w:val="footnote text"/><w:basedOn w:val="Normal"/><w:rPr><w:sz w:val="16"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/></w:tblBorders></w:tblPr></w:style>
</w:styles>"""

NUMBERING = DECL + f"""<w:numbering {W}>
<w:abstractNum w:abstractNumId="0">
  <w:multiLevelType w:val="singleLevel"/>
  <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="(%1)"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>
</w:abstractNum>
<w:abstractNum w:abstractNumId="1">
  <w:multiLevelType w:val="singleLevel"/>
  <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="lowerRoman"/><w:lvlText w:val="(%1)"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>
</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>
</w:numbering>"""

FOOTNOTES = DECL + f"""<w:footnotes {W}>
<w:footnote w:type="separator" w:id="-1"><w:p><w:pPr><w:spacing w:after="0"/></w:pPr><w:r><w:separator/></w:r></w:p></w:footnote>
<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:pPr><w:spacing w:after="0"/></w:pPr><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>
<w:footnote w:id="1"><w:p><w:pPr><w:pStyle w:val="FootnoteText"/></w:pPr><w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteRef/></w:r><w:r><w:t xml:space="preserve"> Restated to reflect the adoption of IFRS 17 Insurance Contracts.</w:t></w:r></w:p></w:footnote>
</w:footnotes>"""

HEADER = DECL + f"""<w:hdr {W}>
<w:p><w:pPr><w:framePr w:wrap="around" w:vAnchor="text" w:hAnchor="margin" w:xAlign="right" w:y="1"/><w:jc w:val="right"/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>ABC Holding PJSC</w:t></w:r></w:p>
<w:p><w:r><w:t>Consolidated financial statements</w:t></w:r></w:p>
</w:hdr>"""

FOOTER = DECL + f"""<w:ftr {W}>
<w:p><w:pPr><w:jc w:val="center"/></w:pPr>
<w:r><w:t xml:space="preserve">Page </w:t></w:r>
<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>
</w:p>
</w:ftr>"""


def _cell(text: str, width: int, *, right: bool = False, bold: bool = False) -> str:
    jc = '<w:jc w:val="right"/>' if right else ""
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    run = f"<w:r>{rpr}<w:t xml:space=\"preserve\">{text}</w:t></w:r>" if text else ""
    return (f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>'
            f"<w:p><w:pPr><w:spacing w:after=\"0\"/>{jc}</w:pPr>{run}</w:p></w:tc>")


def _row(label: str, note: str, cy: str, py: str, *, bold: bool = False) -> str:
    return ("<w:tr>" + _cell(label, 4800, bold=bold) + _cell(note, 900, right=True)
            + _cell(cy, 1800, right=True, bold=bold) + _cell(py, 1800, right=True, bold=bold) + "</w:tr>")


TABLE = (
    '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="9300" w:type="dxa"/><w:tblLook w:val="04A0"/></w:tblPr>'
    '<w:tblGrid><w:gridCol w:w="4800"/><w:gridCol w:w="900"/><w:gridCol w:w="1800"/><w:gridCol w:w="1800"/></w:tblGrid>'
    + _row("", "Notes", "2025 AED'000", "2024 AED'000", bold=True)
    + _row("ASSETS", "", "", "", bold=True)
    + _row("Cash and bank balances", "5", "1,234,567", "987,654")
    + _row("Loans and advances to customers", "6", "8,765,432", "7,654,321")
    + _row("Investment properties", "7", "-", "(12,500)")
    + _row("Total assets", "", "10,000,000", "8,629,475", bold=True)
    + "</w:tbl>"
)

DOCUMENT = DECL + f"""<w:document {W} {R} {W14} {MC} mc:Ignorable="w14">
<w:body>
<w:p w14:paraId="10000001" w:rsidR="00A1" w:rsidRDefault="00A1"><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r w:rsidR="00A1"><w:t>ABC Holding PJSC</w:t></w:r></w:p>
<w:p w:rsidR="00A2"><w:pPr><w:jc w:val="center"/></w:pPr><w:r w:rsidRPr="00B1"><w:t xml:space="preserve">Consolidated statement of </w:t></w:r><w:proofErr w:type="spellStart"/><w:r w:rsidRPr="00B2"><w:t>financial</w:t></w:r><w:proofErr w:type="spellEnd"/><w:r><w:t xml:space="preserve"> position as at 31 December 2025</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Statement of financial position</w:t></w:r></w:p>
{TABLE}
<w:p><w:r><w:t xml:space="preserve">Profit for the </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>year</w:t></w:r><w:r><w:t xml:space="preserve"> attributable to owners of the Company amounted to AED 1,234 million (2024: AED 1,100 million).</w:t></w:r><w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteReference w:id="1"/></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Basis of preparation</w:t></w:r></w:p>
<w:p><w:r><w:t xml:space="preserve">These consolidated financial statements have been prepared in accordance with </w:t></w:r><w:hyperlink r:id="rId6"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr><w:t>IFRS Accounting Standards</w:t></w:r></w:hyperlink><w:r><w:t xml:space="preserve"> as issued by the IASB.</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Financial assets at fair value through profit or loss.</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Financial assets at amortised cost.</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr></w:pPr><w:r><w:t>Level 1: quoted prices in active markets.</w:t></w:r></w:p>
<w:p><w:r><w:t>Cash and bank balances</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>3. Material accounting policies</w:t></w:r></w:p>
<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Inventories</w:t></w:r><w:r><w:t xml:space="preserve"> – Inventories are measured at the lower of cost and net realisable value.</w:t></w:r></w:p>
<w:p/>
<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="5000"/></w:tabs></w:pPr><w:r><w:t>Chairman</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>Chief Executive Officer</w:t></w:r></w:p>
<w:sectPr><w:headerReference w:type="default" r:id="rId4"/><w:footerReference w:type="default" r:id="rId5"/><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/><w:cols w:space="708"/><w:docGrid w:linePitch="360"/></w:sectPr>
</w:body>
</w:document>"""


def build(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = {
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": ROOT_RELS,
        "word/document.xml": DOCUMENT,
        "word/_rels/document.xml.rels": DOC_RELS,
        "word/styles.xml": STYLES,
        "word/numbering.xml": NUMBERING,
        "word/footnotes.xml": FOOTNOTES,
        "word/header1.xml": HEADER,
        "word/footer1.xml": FOOTER,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, xml in parts.items():
            zf.writestr(name, xml.encode("utf-8"))
    return path


if __name__ == "__main__":
    out = build(sys.argv[1] if len(sys.argv) > 1 else "samples/sample_fs.docx")
    print(f"written {out}")
