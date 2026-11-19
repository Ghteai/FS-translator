"""Step 3 tests with a scripted fake model (no Ollama needed)."""
import json
import re
import tempfile
import unittest
from pathlib import Path

from fs_translator.context import parse_context
from fs_translator.pipeline import translate_docx
from fs_translator.prompts import translation_messages
from fs_translator.terms import TermTable
from fs_translator.translators.llm import LLMTranslator, clean_output

import make_sample


class CleanOutputTest(unittest.TestCase):
    def test_strips_wrappers(self):
        self.assertEqual(clean_output('"الأصول"'), "الأصول")
        self.assertEqual(clean_output("Translation: الأصول"), "الأصول")
        self.assertEqual(clean_output("```\nالأصول\n```"), "الأصول")
        self.assertEqual(clean_output("الأصول\nNote: assets is a plural noun."), "الأصول")


class ContextParseTest(unittest.TestCase):
    def test_keeps_short_clean_terms_only(self):
        raw = json.dumps({
            "entity_en": "ABC Holding PJSC", "entity_ar": "ايه بي سي القابضة ش.م.ع", "industry": "bank",
            "key_terms": [
                {"en": "Total assets", "ar": "مجموع الموجودات"},
                {"en": "total assets", "ar": "إجمالي الموجودات"},                 # duplicate
                {"en": "Profit amounted to AED 5 million", "ar": "بلغ الربح 5 ملايين"},  # digits
                {"en": "IFRS", "ar": "IFRS"},                                     # no Arabic
                {"en": "Notes", "ar": "إيضاحات"},
            ],
        }, ensure_ascii=False)
        ctx = parse_context(raw)
        self.assertEqual(ctx.key_terms, [("Total assets", "مجموع الموجودات"), ("Notes", "إيضاحات")])
        self.assertIn("ABC Holding PJSC", ctx.summary)

    def test_json_wrapped_in_text(self):
        ctx = parse_context('Here it is: {"entity_en": "X LLC", "key_terms": []} done')
        self.assertEqual(ctx.entity_en, "X LLC")

    def test_garbage(self):
        self.assertTrue(parse_context("no json here").error)


class TermTableTest(unittest.TestCase):
    def test_longest_first_and_no_overlap(self):
        t = TermTable()
        t.add("current assets", "الموجودات المتداولة", "context")
        t.add("Total current assets", "مجموع الموجودات المتداولة", "context")
        t.add("assets", "الموجودات", "context")
        found = [x.en for x in t.find("Total current assets and other assets")]
        self.assertEqual(found, ["Total current assets", "assets"])

    def test_first_translation_wins(self):
        t = TermTable()
        self.assertTrue(t.learn("Notes", "إيضاحات"))
        self.assertFalse(t.learn("NOTES", "ملاحظات"))
        self.assertEqual(t.find("Notes")[0].ar, "إيضاحات")

    def test_learn_only_short_clean_labels(self):
        t = TermTable()
        self.assertFalse(t.learn("These financial statements were approved by the Board", "..."))
        self.assertFalse(t.learn("Total ⟦N1⟧", "المجموع ⟦N1⟧"))
        self.assertFalse(t.learn("Cash", "Cash نقد"))                     # Latin left in Arabic
        self.assertTrue(t.learn("Cash and bank balances", "النقد والأرصدة لدى البنوك"))


class PromptTest(unittest.TestCase):
    def test_terms_examples_and_feedback(self):
        msgs = translation_messages("Total ⟦N1⟧", summary="Entity: X", terms=[("Total", "المجموع")],
                                    examples=[("Cash", "النقد")], feedback="⟦N1⟧ is missing", previous="المجموع")
        self.assertIn("Entity: X", msgs[0]["content"])
        self.assertIn("- Total = المجموع", msgs[-3]["content"])
        self.assertEqual(msgs[-2], {"role": "assistant", "content": "المجموع"})
        self.assertIn("⟦N1⟧ is missing", msgs[-1]["content"])
        self.assertIn({"role": "assistant", "content": "النقد"}, msgs)       # approved-examples slot


class ScriptedClient:
    """Pretends to be Ollama: answers the context pass and translations by rule."""
    model = "scripted"

    def __init__(self, drop_first_time=False):
        self.translations = []
        self.contexts = 0
        self.drop_first_time = drop_first_time
        self.dropped = set()

    def chat(self, messages, *, json_mode=False, max_tokens=1024):
        if json_mode:
            self.contexts += 1
            return json.dumps({"entity_en": "ABC Holding PJSC", "entity_ar": "ايه بي سي القابضة ش.م.ع",
                               "key_terms": [{"en": "Cash and bank balances", "ar": "النقد والأرصدة لدى البنوك"}]},
                              ensure_ascii=False)
        user = messages[-1]["content"]
        if "Write the corrected" in user:            # retry: translate the original request again
            user = messages[-3]["content"]
        text = user.split("Translate:\n", 1)[1]
        self.translations.append((text, user))
        out = "ترجمة " + text                          # keeps tags and placeholders
        out = re.sub(r"[A-Za-z]+(?![^<]*>)(?![^⟦]*⟧)", "س", out)
        if self.drop_first_time and "⟦N1⟧" in text and text not in self.dropped:
            self.dropped.add(text)
            out = out.replace("⟦N1⟧", "")
        return out


class PipelineLLMTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.sample = make_sample.build(cls.dir / "sample.docx")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_context_once_terms_in_prompt_and_dedup(self):
        client = ScriptedClient()
        report = translate_docx(self.sample, self.dir / "a.docx", LLMTranslator(client))
        self.assertEqual(client.contexts, 1)
        # "Cash and bank balances" appears twice in the document but is translated once
        texts = [t for t, _ in client.translations]
        self.assertEqual(texts.count("Cash and bank balances"), 1)
        prompt = next(u for t, u in client.translations if t == "Cash and bank balances")
        self.assertIn("- Cash and bank balances = النقد والأرصدة لدى البنوك", prompt)
        self.assertEqual(report.summary()["schema_problems"], [])
        self.assertEqual(report.context.entity_en, "ABC Holding PJSC")

    def test_retry_recovers_dropped_placeholder(self):
        client = ScriptedClient(drop_first_time=True)
        report = translate_docx(self.sample, self.dir / "b.docx", LLMTranslator(client))
        self.assertGreater(report.retries, 0)
        self.assertEqual([p.issues for p in report.passages if p.issues], [])

    def test_limit_leaves_rest_in_english_and_counts_it(self):
        client = ScriptedClient()
        report = translate_docx(self.sample, self.dir / "c.docx", LLMTranslator(client), limit=3)
        s = report.summary()
        self.assertEqual(s["model_calls"], 3)
        self.assertGreater(s["passages_left_in_english_by_limit"], 0)


if __name__ == "__main__":
    unittest.main()
