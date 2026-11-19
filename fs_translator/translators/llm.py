"""Translator backed by a local model (Ollama). Same interface as the fake translators."""
from __future__ import annotations

import re

from ..context import DocContext, extract_context
from ..llm import OllamaClient
from ..ooxml import has_arabic
from ..prompts import translation_messages

_FENCE = re.compile(r"^```\w*\s*|\s*```$")
_LABEL = re.compile(r"^\s*(?:arabic|translation|arabic translation|الترجمة)\s*[:：]\s*", re.I)
_QUOTES = "\"'«»“”"


class LLMTranslator:
    target_arabic = True

    def __init__(self, client: OllamaClient | None = None):
        self.client = client or OllamaClient()
        self.name = f"ollama:{self.client.model}"

    def prepare(self, passages) -> DocContext:
        """Document context pass (one call)."""
        return extract_context(passages, self.client)

    def translate(self, text: str, context: dict) -> str:
        messages = translation_messages(
            text,
            summary=context.get("summary", ""),
            terms=context.get("terms"),
            examples=context.get("examples"),          # empty slot until retrieval exists
            feedback=context.get("feedback"),
            previous=context.get("previous"),
        )
        raw = self.client.chat(messages, max_tokens=min(1024, 64 + len(text)))
        return clean_output(raw)


def clean_output(raw: str) -> str:
    """Strip what small models add around the answer: fences, labels, quotes, extra lines."""
    text = _FENCE.sub("", (raw or "").strip()).strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        # A passage is one line; a second line is usually an explanation.
        arabic = [ln for ln in lines if has_arabic(ln)]
        lines = arabic[:1] or lines[:1]
    text = lines[0] if lines else ""
    text = _LABEL.sub("", text).strip()
    if len(text) >= 2 and text[0] in _QUOTES and text[-1] in _QUOTES:
        text = text[1:-1].strip()
    return text
