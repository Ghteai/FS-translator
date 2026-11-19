"""Standard IFRS terminology (glossary/ifrs_terms_en_ar.csv).

The glossary is the first source of fixed terms: it wins over terms the model
proposes in the context pass and over learned labels. Variant "gcc" uses the
`ar` column (UAE, Bahrain, Kuwait, Qatar, Oman); "ksa" uses `ar_ksa` where given
(Saudi/SOCPA usage), falling back to `ar`.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .checks import clean_arabic_term
from .config import FS_GLOSSARY

VARIANTS = ("gcc", "ksa", "none")


def load_glossary(variant: str = "gcc", path: str | Path = FS_GLOSSARY) -> list[tuple[str, str]]:
    if variant == "none":
        return []
    if variant not in VARIANTS:
        raise ValueError(f"unknown terminology variant '{variant}' (use {', '.join(VARIANTS)})")
    path = Path(path)
    if not path.exists():
        return []
    terms = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            en = (row.get("en") or "").strip()
            ar = (row.get("ar") or "").strip()
            if variant == "ksa" and (row.get("ar_ksa") or "").strip():
                ar = row["ar_ksa"].strip()
            if en and ar and clean_arabic_term(ar):
                terms.append((en, ar))
    return terms
