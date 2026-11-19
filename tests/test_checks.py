"""Fixes found on Dummy_FS_2025_first5: foreign scripts, English left, stray brackets,
literal tabs, reference numbers, names."""
import json
import unittest

from fs_translator.checks import clean_arabic_term, foreign_scripts, latin_words, output_problems, stray_brackets
from fs_translator.clean import clean_part
from fs_translator.context import parse_context
from fs_translator.placeholders import lock, restore
from fs_translator.segment import extract_passages
from fs_translator.terms import TermTable

from helpers import body


class ScriptTest(unittest.TestCase):
    def test_detects_scripts_seen_in_qwen_output(self):
        self.assertIn("Chinese", foreign_scripts("في إعداد报表， مجلس الإدارة"))
        self.assertIn("Korean", foreign_scripts("كافية و 적يلة"))
        self.assertIn("Cyrillic", foreign_scripts("سارة سامпл"))
        self.assertEqual(foreign_scripts("بيان المركز المالي، 2025 (12,500)"), {})

    def test_latin_words(self):
        self.assertEqual(latin_words("Conductنا مراجعتنا وفقًا لمعايير ISAs"), ["Conduct"])
        self.assertEqual(latin_words("وفقًا للمعايير IFRS ⟦N1⟧ <b1>هنا</b1>"), [])
        # company initials kept when they are in the source
        self.assertEqual(latin_words("شركة ABC القابضة", "ABC Holding PJSC"), [])
        self.assertEqual(latin_words("شركة ABC القابضة", "Example Holding"), ["ABC"])

    def test_output_problems_and_brackets(self):
        problems = output_problems("وان报表一致 Conduct", "source")
        self.assertTrue(any("Chinese" in p for p in problems))
        self.assertTrue(any("Conduct" in p for p in problems))
        self.assertTrue(stray_brackets("⟧000000-1 تم"))

    def test_terms_must_be_clean_arabic(self):
        self.assertFalse(clean_arabic_term("ال报表"))
        self.assertFalse(clean_arabic_term("النقود والمقادير النقدية相当"))
        self.assertTrue(clean_arabic_term("القوائم المالية"))
        table = TermTable()
        self.assertFalse(table.add("financial statements", "ال报表", "context"))
        self.assertFalse(table.learn("Sara Sample", "سارة سامпл"))

    def test_context_pass_drops_contaminated_terms(self):
        raw = json.dumps({"key_terms": [
            {"en": "financial statements", "ar": "ال报表"},
            {"en": "cash and cash equivalents", "ar": "النقود والمقادير النقدية相当"},
            {"en": "inventories", "ar": "المخزون"},
        ]}, ensure_ascii=False)
        self.assertEqual(parse_context(raw).key_terms, [("inventories", "المخزون")])


class TabAndNumberTest(unittest.TestCase):
    def test_literal_tab_splits_passages(self):
        root = body('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Ahmed Example</w:t></w:r>'
                    '<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">\tSara Sample</w:t></w:r></w:p>')
        stats = clean_part(root)
        self.assertEqual(stats["literal_tabs"], 1)
        self.assertEqual([p.source for p in extract_passages(root, "doc")], ["Ahmed Example", "Sara Sample"])

    def test_reference_numbers_locked_whole(self):
        lk = lock("000000-1 obtained on 12 March 2011")
        self.assertEqual(lk.text, "⟦N1⟧ obtained on ⟦D1⟧")
        self.assertEqual(restore("⟦N1⟧ تم الحصول عليه في ⟦D1⟧", lk)[0], "‎000000-1 تم الحصول عليه في 12 مارس 2011")
        self.assertEqual(restore(lk.text, lk, arabic=False)[0], "000000-1 obtained on 12 March 2011")
        self.assertEqual(restore("⟦N1⟧", lock("-5.25"))[0], "‎-5.25")
        self.assertEqual(restore("⟦N1⟧", lock("(12,500)"))[0], "(12,500)")     # no mark needed


class RetryOnScriptTest(unittest.TestCase):
    def test_chinese_triggers_retry_and_is_flagged_if_it_stays(self):
        import tempfile
        from pathlib import Path

        from fs_translator.pipeline import translate_docx
        from fs_translator.translators.llm import LLMTranslator
        import make_sample

        class ChineseOnce:
            model = "scripted"

            def __init__(self, stubborn):
                self.stubborn, self.retries = stubborn, 0

            def chat(self, messages, *, json_mode=False, max_tokens=1024):
                if json_mode:
                    return "{}"
                retry = "Write the corrected" in messages[-1]["content"]
                self.retries += retry
                user = messages[-3]["content"] if retry else messages[-1]["content"]
                text = user.split("Translate:\n", 1)[1]
                if "Basis of preparation" in text and (self.stubborn or not retry):
                    return "أساس报表"
                return "نص " + " ".join(t for t in text.split() if t.startswith("⟦") or t.startswith("<"))

        with tempfile.TemporaryDirectory() as tmp:
            sample = make_sample.build(Path(tmp) / "s.docx")
            fixed = ChineseOnce(stubborn=False)
            r1 = translate_docx(sample, Path(tmp) / "a.docx", LLMTranslator(fixed))
            p1 = next(p for p in r1.passages if p.source == "Basis of preparation")
            self.assertGreater(fixed.retries, 0)
            self.assertFalse(any("Chinese" in i for i in p1.issues))

            stubborn = ChineseOnce(stubborn=True)
            r2 = translate_docx(sample, Path(tmp) / "b.docx", LLMTranslator(stubborn))
            p2 = next(p for p in r2.passages if p.source == "Basis of preparation")
            self.assertTrue(any("Chinese" in i for i in p2.issues))


if __name__ == "__main__":
    unittest.main()
