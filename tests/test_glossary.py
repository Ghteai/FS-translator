import csv
import json
import tempfile
import unittest
from pathlib import Path

from fs_translator.checks import clean_arabic_term
from fs_translator.config import FS_GLOSSARY
from fs_translator.glossary import load_glossary
from fs_translator.pipeline import translate_docx
from fs_translator.terms import TermTable
from fs_translator.translators.llm import LLMTranslator

import make_sample


class GlossaryFileTest(unittest.TestCase):
    def setUp(self):
        with open(FS_GLOSSARY, encoding="utf-8-sig", newline="") as f:
            self.rows = list(csv.DictReader(f))

    def test_file_is_well_formed(self):
        self.assertGreater(len(self.rows), 200)
        ens = [r["en"].lower() for r in self.rows]
        self.assertEqual(len(ens), len(set(ens)), "duplicate English terms")
        for r in self.rows:
            self.assertIn(r["status"], ("standard", "review"), r["en"])
            for col in ("ar", "ar_ksa"):
                if r[col]:
                    self.assertTrue(clean_arabic_term(r[col]), f"{r['en']}: {r[col]}")

    def test_variants(self):
        gcc = dict(load_glossary("gcc"))
        ksa = dict(load_glossary("ksa"))
        self.assertEqual(gcc["Current assets"], "الموجودات المتداولة")
        self.assertEqual(ksa["Current assets"], "الأصول المتداولة")
        self.assertEqual(gcc["Note"], ksa["Note"])           # no Saudi variant -> same
        self.assertEqual(load_glossary("none"), [])
        with self.assertRaises(ValueError):
            load_glossary("xyz")

    def test_known_errors_from_dummy_fs_are_covered(self):
        gcc = dict(load_glossary("gcc"))
        self.assertEqual(gcc["Note"], "إيضاح")
        self.assertEqual(gcc["BD"], "دينار بحريني")
        self.assertEqual(gcc["Right-of-use assets"], "موجودات حق الاستخدام")
        self.assertEqual(gcc["Gross profit"], "إجمالي الربح")
        self.assertEqual(gcc["W.L.L."], "ذ.م.م")

    def test_matching_longest_first_including_dotted_forms(self):
        table = TermTable()
        for en, ar in load_glossary("gcc"):
            table.add(en, ar, "glossary")
        found = [t.en for t in table.find("Total current assets of Example Trading Company W.L.L.")]
        self.assertEqual(found, ["Total current assets", "W.L.L."])
        text = "The board of directors is responsible ... unless the board of directors intends to liquidate"
        self.assertEqual([t.en for t in table.find(text)], ["Board of directors"])   # no stray "Directors"
        found = [t.en for t in table.find("Statement of profit or loss and other comprehensive income")]
        self.assertEqual(found, ["Statement of profit or loss and other comprehensive income"])


class GlossaryPriorityTest(unittest.TestCase):
    def test_glossary_wins_over_context_and_only_used_terms_reported(self):
        class Client:
            model = "scripted"

            def __init__(self):
                self.prompts = []

            def chat(self, messages, *, json_mode=False, max_tokens=1024):
                if json_mode:   # the model proposes a wrong term for "Total assets"
                    return json.dumps({"key_terms": [{"en": "Total assets", "ar": "الثروات الإجمالية"}]}, ensure_ascii=False)
                self.prompts.append(messages[-1]["content"])
                return "نص"

        with tempfile.TemporaryDirectory() as tmp:
            sample = make_sample.build(Path(tmp) / "s.docx")
            client = Client()
            report = translate_docx(sample, Path(tmp) / "o.docx", LLMTranslator(client), glossary=load_glossary("gcc"))
            prompt = next(p for p in client.prompts if p.endswith("Translate:\nTotal assets"))
            self.assertIn("- Total assets = مجموع الموجودات", prompt)
            self.assertNotIn("الثروات", prompt)
            data = json.loads(report.to_json())
            origins = {t["origin"] for t in data["terms"]}
            self.assertIn("glossary", origins)
            self.assertTrue(all(t["used"] for t in data["terms"] if t["origin"] == "glossary"))
            self.assertLess(len(data["terms"]), 100)              # not all 255 glossary rows


if __name__ == "__main__":
    unittest.main()
