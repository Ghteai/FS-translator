import tempfile
import unittest
from pathlib import Path

from fs_translator.pipeline import translate_docx
from fs_translator.placeholders import lock, restore
from fs_translator.textrules import is_translatable

import make_sample


def locked_values(text):
    return list(lock(text).values.values())


class LockTest(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(locked_values("AED 1,234,567 and (12,500) and -5.25 and 12.5%"),
                         ["1,234,567", "(12,500)", "-5.25", "12.5%"])

    def test_bracket_context_is_not_part_of_number(self):
        lk = lock("(2024: AED 1,100 million)")
        self.assertEqual(lk.text, "(⟦N1⟧: AED ⟦N2⟧ million)")

    def test_dates_in_several_forms(self):
        for text in ["31 December 2025", "31 DECEMBER 2025", "31 Dec. 2025", "December 31, 2025", "December 2025"]:
            lk = lock(text)
            self.assertEqual(lk.text, "⟦D1⟧", text)
            self.assertFalse(lk.needs_model, text)

    def test_dates_restored_in_arabic(self):
        lk = lock("as at 31 December 2025 and 30 June 2024")
        self.assertEqual(lk.text, "as at ⟦D1⟧ and ⟦D2⟧")
        out, issues = restore("كما في ⟦D1⟧ و ⟦D2⟧", lk)
        self.assertEqual(out, "كما في 31 ديسمبر 2025 و 30 يونيو 2024")
        self.assertEqual(issues, [])

    def test_dates_restored_in_english_when_not_arabic(self):
        lk = lock("as at 31 December 2025")
        self.assertEqual(restore(lk.text, lk, arabic=False)[0], "as at 31 December 2025")

    def test_note_subreference_uses_abjad(self):
        lk = lock("see note 12(a)")
        self.assertEqual(lk.text, "see note ⟦N1⟧")
        self.assertEqual(restore("انظر الإيضاح ⟦N1⟧", lk)[0], "انظر الإيضاح 12(أ)")

    def test_numbers_glued_to_letters_or_tags_are_left_alone(self):
        lk = lock("Profit <b1>Q4</b1> under IFRS 9")
        self.assertEqual(lk.text, "Profit <b1>Q4</b1> under IFRS ⟦N1⟧")

    def test_words_that_look_like_months_are_not_dates(self):
        self.assertEqual(lock("The Group may 5 times").text, "The Group may ⟦N1⟧ times")
        self.assertEqual(lock("May 5").text, "May ⟦N1⟧")      # month-first needs a year

    def test_iso_and_slash_dates_kept_whole(self):
        self.assertEqual(locked_values("on 31/12/2025 or 2025-12-31"), ["31/12/2025", "2025-12-31"])

    def test_needs_model(self):
        self.assertTrue(lock("Total for 2025").needs_model)
        self.assertFalse(lock("(12,500)").needs_model)
        self.assertFalse(lock("<b1>31 December 2025</b1>").needs_model)


class RestoreTest(unittest.TestCase):
    def setUp(self):
        self.lk = lock("Revenue of AED 1,234 million in 2025")       # ⟦N1⟧, ⟦N2⟧

    def test_round_trip(self):
        out, issues = restore("إيرادات بقيمة ⟦N1⟧ مليون درهم في ⟦N2⟧", self.lk)
        self.assertEqual(out, "إيرادات بقيمة 1,234 مليون درهم في 2025")
        self.assertEqual(issues, [])

    def test_spacing_inside_brackets_tolerated(self):
        out, issues = restore("⟦ N1 ⟧ ⟦N2⟧", self.lk)
        self.assertEqual((out, issues), ("1,234 2025", []))

    def test_missing_number_flagged(self):
        _, issues = restore("إيرادات بقيمة ⟦N1⟧ مليون درهم", self.lk)
        self.assertEqual(issues, ["missing number '2025'"])

    def test_number_typed_by_model_instead_of_placeholder_flagged(self):
        _, issues = restore("إيرادات بقيمة 1,235 مليون درهم في ⟦N2⟧", self.lk)
        self.assertEqual(issues, ["missing number '1,234'"])

    def test_duplicate_and_unknown_flagged(self):
        _, issues = restore("⟦N1⟧ ⟦N1⟧ ⟦N2⟧ ⟦N9⟧", self.lk)
        self.assertEqual(sorted(issues), ["'1,234' appears 2 times (once in source)",
                                          "unknown placeholder ⟦N9⟧ in translation"])


class NonTextTest(unittest.TestCase):
    def test_cells_never_sent(self):
        for text in ["1,234,567", "(12,500)", "-", "—", "AED'000", "2025 AED'000", "US$ 000", "12.5%", "5(a)"]:
            self.assertFalse(is_translatable(text) and lock(text).needs_model, text)

    def test_text_cells_sent(self):
        for text in ["Notes", "Total assets", "AED 5 million", "Restated"]:
            self.assertTrue(is_translatable(text) and lock(text).needs_model, text)


class DroppingTranslator:
    """A bad model: forgets every number."""
    name = "drops-numbers"

    def translate(self, text, context):
        import re
        return re.sub(r"⟦[ND]\d+⟧", "", text)


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.sample = make_sample.build(Path(cls.tmp.name) / "sample.docx")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_model_never_sees_figures(self):
        seen = []

        class Spy:
            name = "spy"

            def translate(self, text, context):
                seen.append(text)
                return text

        translate_docx(self.sample, Path(self.tmp.name) / "spy.docx", Spy(), rtl=False)
        for text in seen:
            self.assertNotRegex(text, r"\d,\d{3}", text)       # no amounts
            self.assertNotIn("2025", text)
            self.assertNotIn("December", text)

    def test_dropped_numbers_are_flagged(self):
        report = translate_docx(self.sample, Path(self.tmp.name) / "bad.docx", DroppingTranslator())
        flagged = [p for p in report.passages if p.issues]
        self.assertTrue(any("missing number '1,234'" in i for p in flagged for i in p.issues))
        self.assertTrue(any("missing date '31 December 2025'" in i for p in flagged for i in p.issues))


if __name__ == "__main__":
    unittest.main()
