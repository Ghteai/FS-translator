"""All prompts in one place, so they can be read, tuned and shown in the demo."""
from __future__ import annotations

import json

# --- 1. Document context pass ---------------------------------------------------

CONTEXT_SYSTEM = """You analyse English financial statements before they are translated into Arabic.
Answer with one JSON object only, no other text."""

CONTEXT_USER = """Read the start of this financial statements document and return JSON with these keys:
- "entity_en": the reporting entity's full legal name in English
- "entity_ar": the entity's name in formal Arabic (legal form abbreviations as used in the Gulf, e.g. PJSC -> ش.م.ع, BSC -> ش.م.ب, WLL -> ذ.م.م, SAOG -> ش.م.ع.ع)
- "period_en": the reporting period or date, e.g. "year ended 31 December 2025"
- "industry": one of bank, insurance, investment, real estate, trading, manufacturing, services, other
- "framework": the accounting framework, e.g. IFRS Accounting Standards
- "currency": the presentation currency code, e.g. AED
- "key_terms": a list of 15 to 30 objects {{"en": ..., "ar": ...}} with the recurring financial terms in this document (statement titles, line items, headings) and the standard Arabic used in audited financial statements in the GCC. Each term is a short noun phrase of at most 6 words, never a sentence, and contains no numbers or dates.

Document start:
\"\"\"
{text}
\"\"\""""


def context_messages(text: str) -> list[dict]:
    return [
        {"role": "system", "content": CONTEXT_SYSTEM},
        {"role": "user", "content": CONTEXT_USER.format(text=text)},
    ]


# --- 2. Passage translation -------------------------------------------------------

TRANSLATE_SYSTEM = """You translate audited financial statements from English into formal Arabic (Modern Standard Arabic, the style used in published GCC financial statements).

Rules:
1. Output only the Arabic translation of the text. No explanations, notes, quotes or English.
2. Placeholders such as ⟦N1⟧ or ⟦D1⟧ stand for numbers and dates. Copy each one exactly once, unchanged, at the right place in the Arabic sentence. Never write digits yourself.
3. Tags such as <b1>...</b1> or <a1>...</a1> mark formatted words. Put each pair of tags around the Arabic words that translate the tagged English words. Keep every tag exactly once.
4. When a fixed term is given, use that Arabic term. You may add the article ال or a prefix (و، ب، ل، ف) or adjust it to the grammar of the sentence, but never replace it with a different word.
5. Keep standard acronyms such as IFRS, IAS and ISA in Latin letters.
6. Translate headings written in capital letters as normal Arabic headings.
7. Write only in Arabic script (plus placeholders, tags and the acronyms above). Never use Chinese, English or any other language.
8. Names of people, companies, banks and places: transliterate them into Arabic letters, do not translate their meaning. Legal forms in their Arabic form: W.L.L. -> ذ.م.م, B.S.C. -> ش.م.ب, PJSC -> ش.م.ع, LLC -> ذ.م.م."""

# Format demonstrations (not translation memory): they teach the model how to
# carry placeholders and tags, which small models otherwise drop.
FORMAT_EXAMPLES = [
    ("Profit for the <b1>year</b1> ended ⟦D1⟧",
     "ربح <b1>السنة</b1> المنتهية في ⟦D1⟧"),
    ("Revenue increased to AED ⟦N1⟧ million (⟦N2⟧: AED ⟦N3⟧ million).",
     "ارتفعت الإيرادات إلى ⟦N1⟧ مليون درهم (⟦N2⟧: ⟦N3⟧ مليون درهم)."),
]


def translation_messages(
    text: str,
    *,
    summary: str = "",
    terms: list[tuple[str, str]] | None = None,
    examples: list[tuple[str, str]] | None = None,
    feedback: str | None = None,
    previous: str | None = None,
) -> list[dict]:
    """Build the chat for one passage.

    `examples` is the slot for similar approved translations (retrieval, later
    phase); it is empty in the POC.
    """
    system = TRANSLATE_SYSTEM
    if summary:
        system += "\n\nDocument:\n" + summary
    messages = [{"role": "system", "content": system}]

    for en, ar in FORMAT_EXAMPLES + list(examples or []):
        messages.append({"role": "user", "content": _user_block(en, [])})
        messages.append({"role": "assistant", "content": ar})

    messages.append({"role": "user", "content": _user_block(text, terms or [])})
    if feedback and previous is not None:
        messages.append({"role": "assistant", "content": previous})
        messages.append({"role": "user", "content": feedback + "\nWrite the corrected Arabic translation only."})
    return messages


def _user_block(text: str, terms: list[tuple[str, str]]) -> str:
    block = ""
    if terms:
        block += "Fixed terms:\n" + "\n".join(f"- {en} = {ar}" for en, ar in terms) + "\n\n"
    return block + "Translate:\n" + text


def summary_text(ctx: dict) -> str:
    """One compact paragraph of document facts for every passage prompt."""
    parts = []
    if ctx.get("entity_en"):
        name = ctx["entity_en"]
        if ctx.get("entity_ar"):
            name += f" (Arabic: {ctx['entity_ar']})"
        parts.append(f"Entity: {name}")
    for key, label in (("period_en", "Period"), ("industry", "Industry"),
                       ("framework", "Framework"), ("currency", "Currency")):
        if ctx.get(key):
            parts.append(f"{label}: {ctx[key]}")
    return "\n".join(parts)


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
