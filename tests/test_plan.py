"""Formatting and numbering fixes: run-in headings, section numbers, extra tags."""
import re
import tempfile
import unittest
from pathlib import Path

from fs_translator.pipeline import translate_docx
from fs_translator.placeholders import lock
from fs_translator.plan import plan, sub_locked
from fs_translator.translators.llm import LLMTranslator

import make_sample


def pieces(source):
    return [(p.text, p.translate) for p in plan(lock(source))]


class PlanTest(unittest.TestCase):
    def test_run_in_heading_with_dash(self):
        self.assertEqual(pieces("<b1>Inventories</b1> – Inventories are measured at cost."), [
            ("<b1>", False), ("Inventories", True), ("</b1> – ", False), ("Inventories are measured at cost.", True)])

    def test_run_in_heading_with_colon_inside_tag(self):
        self.assertEqual(pieces("<b1>Credit risk:</b1> the risk of loss."), [
            ("<b1>", False), ("Credit risk:", True), ("</b1> ", False), ("the risk of loss.", True)])

    def test_other_tags_stay_with_the_sentence(self):
        got = pieces("<b1>Inventories</b1> – measured at the <i1>lower of cost</i1>.")
        self.assertEqual(got[-1], ("measured at the <i1>lower of cost</i1>.", True))

    def test_no_split_inside_a_sentence(self):
        self.assertEqual(pieces("Profit for the <b1>year</b1> – restated"), [("Profit for the <b1>year</b1> – restated", True)])
        self.assertEqual(pieces("<b1>Inventories</b1> are measured at cost"),          # no separator: one sentence
                         [("<b1>Inventories</b1> are measured at cost", True)])

    def test_section_numbers(self):
        self.assertEqual(pieces("3. Material accounting policies"), [("⟦N1⟧. ", False), ("Material accounting policies", True)])
        self.assertEqual(pieces("4.1 Basis of preparation"), [("⟦N1⟧ ", False), ("Basis of preparation", True)])
        self.assertEqual(pieces("(a) Basis of preparation"), [("(a) Basis of preparation", True)])   # left to the model

    def test_amounts_and_years_are_not_section_numbers(self):
        self.assertEqual(pieces("2025 was a good year"), [("⟦N1⟧ was a good year", True)])
        self.assertEqual(pieces("1,234 units were sold"), [("⟦N1⟧ units were sold", True)])

    def test_number_and_heading_together(self):
        got = pieces("3. <b1>Leases</b1> – At commencement, a lease liability is recognised.")
        self.assertEqual([t for t, tr in got if tr], ["Leases", "At commencement, a lease liability is recognised."])

    def test_sub_locked_keeps_only_its_placeholders(self):
        lk = lock("<b1>Leases</b1> – paid ⟦N9⟧ on 31 December 2025".replace("⟦N9⟧", "1,000"))
        tail = plan(lk)[-1].text
        self.assertEqual(set(sub_locked(lk, tail).values), {"⟦N1⟧", "⟦D1⟧"})


class CarelessClient:
    """Behaves like a 7B model on long sentences: drops every tag and a leading number."""
    model = "scripted"

    def __init__(self):
        self.seen = []

    def chat(self, messages, *, json_mode=False, max_tokens=1024):
        if json_mode:
            return "{}"
        user = messages[-3]["content"] if "Write the corrected" in messages[-1]["content"] else messages[-1]["content"]
        text = user.split("Translate:\n", 1)[1]
        self.seen.append(text)
        text = re.sub(r"^⟦N\d+⟧\.?\s*", "", text)                  # loses the section number
        text = re.sub(r"</?[a-z]+\d+>", "", text)                 # loses all formatting tags
        out = re.sub(r"[A-Za-z]+", "س", text)
        return ("<b1>" + out + "</b1>") if "Total" in user else out  # invents a tag sometimes


class PipelineFixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.sample = make_sample.build(Path(cls.tmp.name) / "sample.docx")
        cls.client = CarelessClient()
        cls.report = translate_docx(cls.sample, Path(cls.tmp.name) / "o.docx", LLMTranslator(cls.client))
        cls.by_source = {p.source: p for p in cls.report.passages}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_run_in_heading_keeps_bold_even_when_model_drops_tags(self):
        p = self.by_source["<b1>Inventories</b1> – Inventories are measured at the lower of cost and net realisable value."]
        self.assertEqual(p.issues, [])
        self.assertTrue(p.target.startswith("<b1>") and "</b1> – " in p.target)
        self.assertIn("Inventories", self.client.seen)                          # heading sent on its own
        bold_run = p.slots[0].units[0]
        self.assertTrue(bold_run.text and "Invent" not in bold_run.text)        # Arabic heading sits in the bold run

    def test_section_number_kept_even_when_model_drops_it(self):
        p = self.by_source["3. Material accounting policies"]
        self.assertEqual(p.issues, [])
        self.assertTrue(p.target.startswith("3. "))
        self.assertIn("Material accounting policies", self.client.seen)        # model never saw the number

    def test_invented_tags_removed_without_a_flag(self):
        p = self.by_source["Total assets"]
        self.assertEqual(p.issues, [])
        self.assertNotIn("<b1>", p.target)


if __name__ == "__main__":
    unittest.main()
