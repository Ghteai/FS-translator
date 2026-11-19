"""Whole-document tests on the generated sample FS."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from fs_translator.ooxml import has_arabic, w
from fs_translator.pipeline import roundtrip_docx, translate_docx
from fs_translator.translators import IdentityTranslator, PseudoArabicTranslator

import make_sample


def _parts(path):
    with zipfile.ZipFile(path) as zf:
        return [i.filename for i in zf.infolist()], {n: zf.read(n) for n in zf.namelist()}


def _c14n(data: bytes) -> bytes:
    return etree.tostring(etree.fromstring(data), method="c14n")


def _paragraph_texts(data: bytes) -> list[str]:
    root = etree.fromstring(data)
    return ["".join(t.text or "" for t in p.iter(w("t"))) for p in root.iter(w("p"))]


class RoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.sample = make_sample.build(cls.dir / "sample.docx")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_plain_roundtrip_is_identical(self):
        out = roundtrip_docx(self.sample, self.dir / "rt.docx")
        names_a, a = _parts(self.sample)
        names_b, b = _parts(out)
        self.assertEqual(names_a, names_b)                    # same parts, same order
        for name in names_a:
            if name.endswith(".xml"):
                self.assertEqual(_c14n(a[name]), _c14n(b[name]), name)
            else:
                self.assertEqual(a[name], b[name], name)

    def test_identity_translation_keeps_all_text(self):
        out = self.dir / "identity.docx"
        report = translate_docx(self.sample, out, IdentityTranslator(), rtl=False)
        _, a = _parts(self.sample)
        _, b = _parts(out)
        for part in ("word/document.xml", "word/header1.xml", "word/footer1.xml", "word/footnotes.xml"):
            self.assertEqual(_paragraph_texts(a[part]), _paragraph_texts(b[part]), part)
        self.assertEqual(report.summary()["passages_flagged"], 0)

    def test_pseudo_arabic_document(self):
        out = self.dir / "pseudo.docx"
        report = translate_docx(self.sample, out, PseudoArabicTranslator())
        s = report.summary()
        self.assertEqual(s["schema_problems"], [])
        self.assertEqual(s["passages_flagged"], 0)
        self.assertGreater(s["passages_skipped_non_text"], 0)

        _, b = _parts(out)
        doc = etree.fromstring(b["word/document.xml"])
        all_text = "".join(t.text or "" for t in doc.iter(w("t")))
        for amount in ("1,234,567", "(12,500)", "10,000,000", "31", "2025"):
            self.assertIn(amount, all_text)                    # figures untouched
        self.assertTrue(has_arabic(all_text))
        self.assertIsNotNone(doc.find(f".//{w('tblPr')}/{w('bidiVisual')}"))
        self.assertIsNotNone(doc.find(f".//{w('sectPr')}/{w('bidi')}"))

        numbering = etree.fromstring(b["word/numbering.xml"])
        formats = [f.get(w("val")) for f in numbering.iter(w("numFmt"))]
        self.assertEqual(formats, ["arabicAbjad", "decimal"])

        header = etree.fromstring(b["word/header1.xml"])
        self.assertEqual(header.find(f".//{w('framePr')}").get(w("xAlign")), "left")


if __name__ == "__main__":
    unittest.main()
