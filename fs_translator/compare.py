"""Compare translation runs of the same document (one report.json per model/setting).

    python -m fs_translator compare output/a.report.json output/b.report.json

Columns: time, model calls, retries, server errors, flagged passages, passages
with foreign script (Chinese etc.), passages with English left, and how often
the Arabic of a fixed glossary term actually appears in the translation.
"""
from __future__ import annotations

import json
from pathlib import Path

from .checks import foreign_scripts, latin_words


def summarise(report_path: str | Path) -> dict:
    r = json.loads(Path(report_path).read_text(encoding="utf-8"))
    items = [i for i in r["items"] if i["translatable"] and i.get("target")]
    honoured = given = 0
    for i in items:
        for t in i.get("terms", []):
            given += 1
            honoured += _term_present(t["ar"], i["target"])
    kinds = {"tags": 0, "numbers": 0}
    for i in r["items"]:
        for issue in i["issues"]:
            if "tags" in issue:
                kinds["tags"] += 1
            elif "missing" in issue or "appears" in issue:
                kinds["numbers"] += 1
    return {
        "run": Path(report_path).name.replace(".report.json", "").replace("report.json", Path(report_path).parent.name),
        "model": r.get("translator", "").removeprefix("ollama:"),
        "minutes": round(r.get("seconds", 0) / 60, 1),
        "calls": r.get("model_calls", 0),
        "retries": r.get("retries", 0),
        "errors": r.get("model_errors", 0),
        "flagged": f"{r.get('passages_flagged', 0)}/{len(items)}",
        "foreign_script": sum(1 for i in items if foreign_scripts(i["target"])),
        "english_left": sum(1 for i in items if latin_words(i["target"], i["source"])),
        "tag_flags": kinds["tags"],
        "number_flags": kinds["numbers"],
        "terms_followed": f"{round(100 * honoured / given)}%" if given else "-",
    }


def _term_present(term_ar: str, target: str) -> bool:
    """The term's main words occur in the Arabic (ignoring the article ال and short words)."""
    core = target.replace("ال", "")
    words = [w for w in term_ar.replace("ال", "").split() if len(w) > 2]
    return all(w in core for w in words) if words else True


def table(rows: list[dict]) -> str:
    cols = list(rows[0])
    width = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    line = lambda r: "  ".join(str(r[c]).ljust(width[c]) for c in cols)  # noqa: E731
    return "\n".join([line({c: c for c in cols}), line({c: "-" * width[c] for c in cols}), *map(line, rows)])
