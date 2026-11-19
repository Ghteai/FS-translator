import unittest

from fs_translator.clean import clean_part
from fs_translator.ooxml import ensure_child, w
from fs_translator.rtl import apply_rtl_part, apply_rtl_run
from fs_translator.segment import extract_passages
from fs_translator.textrules import is_translatable
from fs_translator.validate import order_problems
from fs_translator.writeback import TagError, apply_translation, parse_tagged

from helpers import body, child_names, texts


class SchemaOrderTest(unittest.TestCase):
    def test_rpr_insertion_respects_order_and_extensions(self):
        root = body('<w:p><w:r><w:rPr><w:rFonts w:ascii="X"/><w:sz w:val="20"/>'
                    '<w14:ligatures w14:val="all"/></w:rPr><w:t>a</w:t></w:r></w:p>')
        rpr = root.find(".//" + w("rPr"))
        ensure_child(rpr, "rtl")
        ensure_child(rpr, "b")
        ensure_child(rpr, "lang")
        self.assertEqual(child_names(rpr), ["rFonts", "b", "sz", "rtl", "lang", "ligatures"])

    def test_ppr_bidi_goes_before_spacing_and_jc(self):
        root = body('<w:p><w:pPr><w:pStyle w:val="A"/><w:spacing w:after="0"/><w:jc w:val="left"/>'
                    '<w:rPr><w:b/></w:rPr></w:pPr></w:p>')
        ppr = root.find(".//" + w("pPr"))
        ensure_child(ppr, "bidi")
        self.assertEqual(child_names(ppr), ["pStyle", "bidi", "spacing", "jc", "rPr"])

    def test_existing_child_is_reused(self):
        root = body('<w:p><w:pPr><w:bidi/></w:pPr></w:p>')
        ppr = root.find(".//" + w("pPr"))
        ensure_child(ppr, "bidi")
        self.assertEqual(child_names(ppr), ["bidi"])

    def test_validator_reports_wrong_order(self):
        root = body('<w:p><w:pPr><w:jc w:val="left"/><w:bidi/></w:pPr></w:p>')
        self.assertEqual(len(order_problems(root)), 1)


class CleanTest(unittest.TestCase):
    def test_proof_errors_and_rsids_removed_and_runs_merged(self):
        root = body('<w:p w:rsidR="001"><w:r w:rsidRPr="1"><w:t xml:space="preserve">Statement of </w:t></w:r>'
                    '<w:proofErr w:type="spellStart"/><w:r w:rsidRPr="2"><w:t>financial</w:t></w:r>'
                    '<w:proofErr w:type="spellEnd"/><w:r><w:rPr><w:lang w:val="en-US"/></w:rPr>'
                    '<w:t xml:space="preserve"> position</w:t></w:r></w:p>')
        stats = clean_part(root)
        self.assertEqual(texts(root), ["Statement of financial position"])
        self.assertEqual(stats["removed_markers"], 2)
        self.assertNotIn(w("rsidR"), root.find(".//" + w("p")).attrib)

    def test_different_formatting_not_merged(self):
        root = body('<w:p><w:r><w:t>Profit for the </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>year</w:t></w:r></w:p>')
        clean_part(root)
        self.assertEqual(len(texts(root)), 2)

    def test_runs_with_tabs_not_merged(self):
        root = body('<w:p><w:r><w:t>A</w:t><w:tab/></w:r><w:r><w:t>B</w:t></w:r></w:p>')
        clean_part(root)
        self.assertEqual(len(texts(root)), 2)


class SegmentTest(unittest.TestCase):
    def _sources(self, xml):
        return [p.source for p in extract_passages(body(xml), "doc")]

    def test_split_at_tab_and_break(self):
        xml = ('<w:p><w:r><w:t>Chairman</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>Director</w:t>'
               '<w:br/><w:t>Second line</w:t></w:r></w:p>')
        self.assertEqual(self._sources(xml), ["Chairman", "Director", "Second line"])

    def test_inline_bold_tagged(self):
        xml = ('<w:p><w:r><w:t xml:space="preserve">Profit for the </w:t></w:r>'
               '<w:r><w:rPr><w:b/></w:rPr><w:t>year</w:t></w:r></w:p>')
        self.assertEqual(self._sources(xml), ["Profit for the <b1>year</b1>"])

    def test_deleted_text_instructions_and_simple_fields_skipped(self):
        xml = ('<w:p><w:r><w:t xml:space="preserve">Total </w:t></w:r>'
               '<w:del><w:r><w:delText>old </w:delText></w:r></w:del>'
               '<w:r><w:t>equity</w:t></w:r>'
               '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>PAGE</w:instrText></w:r>'
               '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
               '<w:fldSimple w:instr="NUMPAGES"><w:r><w:t>9</w:t></w:r></w:fldSimple></w:p>')
        self.assertEqual(self._sources(xml), ["Total equity"])

    def test_hyperlink_text_kept_in_sentence(self):
        xml = ('<w:p><w:r><w:t xml:space="preserve">See </w:t></w:r><w:hyperlink><w:r><w:rPr>'
               '<w:rStyle w:val="Hyperlink"/></w:rPr><w:t>note 5</w:t></w:r></w:hyperlink></w:p>')
        self.assertEqual(self._sources(xml), ["See <a1>note 5</a1>"])

    def test_number_only_cells_not_translatable(self):
        for text in ["1,234,567", "(12,500)", "-", "AED'000", "2025 AED'000", "US$ 000", "—"]:
            self.assertFalse(is_translatable(text), text)
        for text in ["Notes", "Total assets", "AED 5 million", "IFRS 9"]:
            self.assertTrue(is_translatable(text), text)


class WritebackTest(unittest.TestCase):
    XML = ('<w:p><w:r><w:t xml:space="preserve">Profit for the </w:t></w:r>'
           '<w:r><w:rPr><w:b/></w:rPr><w:t>year</w:t></w:r>'
           '<w:r><w:t xml:space="preserve"> ended</w:t></w:r></w:p>')

    def _passage(self, xml=None):
        root = body(xml or self.XML)
        return root, extract_passages(root, "doc")[0]

    def test_parse_tagged(self):
        self.assertEqual(parse_tagged("a <b1>b</b1> c", ["b1"]), [(None, "a "), ("b1", "b"), (None, " c")])
        with self.assertRaises(TagError):
            parse_tagged("a <b1>b c", ["b1"])
        with self.assertRaises(TagError):
            parse_tagged("a b c", ["b1"])

    def test_same_order_fills_runs_in_place(self):
        root, p = self._passage()
        issues = apply_translation(p, "ربح <b1>السنة</b1> المنتهية")
        self.assertEqual(issues, [])
        self.assertEqual(texts(root), ["ربح ", "السنة", " المنتهية"])

    def test_text_without_source_slot_gets_new_base_run(self):
        root, p = self._passage('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Year</w:t></w:r>'
                                '<w:r><w:t xml:space="preserve"> ended</w:t></w:r></w:p>')
        self.assertEqual(p.source, "<b1>Year</b1> ended")
        apply_translation(p, "عن <b1>السنة</b1> المنتهية")
        runs = root.findall(".//" + w("r"))
        self.assertEqual(texts(root), ["عن ", "السنة", " المنتهية"])
        self.assertIsNone(runs[0].find(w("rPr")))           # new run uses base (non-bold) formatting

    def test_reordered_tags_rebuild_and_flag(self):
        xml = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>A</w:t></w:r><w:r><w:t xml:space="preserve"> and </w:t></w:r>'
               '<w:r><w:rPr><w:i/></w:rPr><w:t>B</w:t></w:r></w:p>')
        root, p = self._passage(xml)
        self.assertEqual(p.source, "<b1>A</b1> and <i1>B</i1>")
        issues = apply_translation(p, "<i1>ب</i1> و <b1>أ</b1>")
        self.assertEqual(len(issues), 1)
        self.assertEqual("".join(texts(root)), "ب و أ")

    def test_broken_tags_fall_back_to_plain_text(self):
        root, p = self._passage()
        issues = apply_translation(p, "ربح <b1>السنة المنتهية")
        self.assertEqual(len(issues), 1)
        self.assertEqual("".join(texts(root)), "ربح السنة المنتهية")


class RtlTest(unittest.TestCase):
    def test_run_gets_complex_script_formatting(self):
        root = body('<w:p><w:r><w:rPr><w:rFonts w:ascii="Calibri" w:cstheme="minorBidi"/><w:b/><w:sz w:val="22"/>'
                    '</w:rPr><w:t>ربح</w:t></w:r></w:p>')
        apply_rtl_run(root.find(".//" + w("r")))
        rpr = root.find(".//" + w("rPr"))
        self.assertEqual(child_names(rpr), ["rFonts", "b", "bCs", "sz", "szCs", "rtl", "lang"])
        fonts = rpr.find(w("rFonts"))
        self.assertEqual(fonts.get(w("cs")), "Arial")
        self.assertIsNone(fonts.get(w("cstheme")))
        self.assertEqual(rpr.find(w("szCs")).get(w("val")), "22")

    def test_number_cells_stay_ltr_and_table_mirrors(self):
        root = body('<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr><w:tr>'
                    '<w:tc><w:p><w:r><w:t>النقد</w:t></w:r></w:p></w:tc>'
                    '<w:tc><w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:r><w:t>1,234</w:t></w:r></w:p></w:tc>'
                    '<w:tc><w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:r><w:t>إيضاح</w:t></w:r></w:p></w:tc>'
                    '</w:tr></w:tbl><w:p><w:r><w:t>نص</w:t></w:r></w:p>')
        apply_rtl_part(root)
        tblpr = root.find(".//" + w("tblPr"))
        self.assertEqual(child_names(tblpr), ["bidiVisual", "tblW"])
        paras = root.findall(".//" + w("p"))
        has_bidi = [p.find(f"{w('pPr')}/{w('bidi')}") is not None for p in paras]
        self.assertEqual(has_bidi, [True, False, True, True])
        # right-aligned Arabic cell heading stays physically right (jc flips in bidi)
        self.assertEqual(paras[2].find(f"{w('pPr')}/{w('jc')}").get(w("val")), "left")
        self.assertEqual(order_problems(root), [])


if __name__ == "__main__":
    unittest.main()
