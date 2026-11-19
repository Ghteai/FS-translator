"""Document context pass: one model call over the start of the document.

Extracts entity name (EN/AR), period, industry, framework, currency and the key
terms with their chosen Arabic. Every passage prompt includes the summary, and
the key terms become the document's fixed terms.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .checks import clean_arabic_term
from .ooxml import has_arabic
from .prompts import context_messages, summary_text
from .segment import Passage
from .writeback import strip_tags

MAX_TERM_WORDS = 6
CONTEXT_CHARS = 6000          # ~1,500 tokens of English: fits a 4k context with room for the answer


@dataclass
class DocContext:
    entity_en: str = ""
    entity_ar: str = ""
    period_en: str = ""
    industry: str = ""
    framework: str = ""
    currency: str = ""
    key_terms: list[tuple[str, str]] = field(default_factory=list)
    raw: str = ""                 # model answer, kept for the report
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "entity_en": self.entity_en, "entity_ar": self.entity_ar, "period_en": self.period_en,
            "industry": self.industry, "framework": self.framework, "currency": self.currency,
            "key_terms": [{"en": en, "ar": ar} for en, ar in self.key_terms],
            "error": self.error,
        }

    @property
    def summary(self) -> str:
        return summary_text(self.as_dict())


def opening_text(passages: list[Passage], limit: int = CONTEXT_CHARS) -> str:
    """The first unique text passages, one per line, up to `limit` characters."""
    lines, seen, size = [], set(), 0
    for p in passages:
        if not p.translatable:
            continue
        text = strip_tags(p.source)
        if text in seen:
            continue
        seen.add(text)
        if size + len(text) > limit:
            break
        lines.append(text)
        size += len(text) + 1
    return "\n".join(lines)


def extract_context(passages: list[Passage], client) -> DocContext:
    text = opening_text(passages)
    if not text:
        return DocContext(error="no text found")
    raw = client.chat(context_messages(text), json_mode=True, max_tokens=1500)
    return parse_context(raw)


def parse_context(raw: str) -> DocContext:
    ctx = DocContext(raw=raw)
    data = _load_json(raw)
    if not isinstance(data, dict):
        ctx.error = "context answer was not valid JSON"
        return ctx
    for key in ("entity_en", "entity_ar", "period_en", "industry", "framework", "currency"):
        value = data.get(key)
        if isinstance(value, str):
            setattr(ctx, key, value.strip())
    if ctx.entity_ar and not has_arabic(ctx.entity_ar):
        ctx.entity_ar = ""
    seen = set()
    for item in data.get("key_terms") or []:
        if not isinstance(item, dict):
            continue
        en, ar = str(item.get("en", "")).strip(), str(item.get("ar", "")).strip()
        # Terms are short phrases; sentences and anything with digits would let
        # figures bypass the placeholders, so they are dropped.
        if (en and has_arabic(ar) and clean_arabic_term(ar) and not re.search(r"[0-9٠-٩]", ar) and not re.search(r"\d", en)
                and len(en.split()) <= MAX_TERM_WORDS and en.lower() not in seen):
            seen.add(en.lower())
            ctx.key_terms.append((en, ar))
    return ctx


def _load_json(raw: str):
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    m = re.search(r"\{.*\}", raw or "", re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None
