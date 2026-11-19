"""The one interface every translation backend implements, so models can be swapped."""
from __future__ import annotations

from typing import Protocol


class Translator(Protocol):
    name: str
    # Optional: set False on a translator whose output is not Arabic (dates are
    # then restored in their source form). Defaults to True when absent.

    def translate(self, text: str, context: dict) -> str:
        """Translate one tagged passage (keeps <b1>..</b1> tags and ⟦N1⟧ placeholders)."""
        ...
