"""End-to-end: read .docx -> clean -> segment -> context -> translate -> write back -> RTL -> save."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .checks import output_problems, stray_brackets
from .clean import clean_part
from .context import DocContext
from .package import DocxPackage
from .placeholders import Locked, lock, restore
from .plan import plan, sub_locked, tags_in
from .rtl import apply_rtl_numbering, apply_rtl_part, apply_rtl_styles
from .segment import Passage, extract_passages
from .terms import TermTable
from .translators.base import Translator
from .validate import order_problems
from .writeback import TagError, apply_translation, parse_tagged, strip_tags

# progress(done, total, passage, seconds_for_this_call)
Progress = Callable[[int, int, Passage, float], None]


@dataclass
class Report:
    source: str
    output: str
    translator: str
    passages: list[Passage] = field(default_factory=list)
    clean: dict = field(default_factory=dict)
    rtl: dict = field(default_factory=dict)
    schema_problems: list[str] = field(default_factory=list)
    context: DocContext | None = None
    terms: TermTable | None = None
    model_calls: int = 0
    retries: int = 0
    model_errors: int = 0
    not_translated_limit: int = 0
    seconds: float = 0.0

    def summary(self) -> dict:
        translatable = [p for p in self.passages if p.translatable]
        return {
            "source": self.source,
            "output": self.output,
            "translator": self.translator,
            "passages_total": len(self.passages),
            "passages_translated": len(translatable) - self.not_translated_limit,
            "passages_skipped_non_text": len(self.passages) - len(translatable),
            "passages_left_in_english_by_limit": self.not_translated_limit,
            "model_calls": self.model_calls,
            "retries": self.retries,
            "model_errors": self.model_errors,
            "seconds": round(self.seconds, 1),
            "numbers_and_dates_locked": sum(len(p.placeholders) for p in translatable),
            "fixed_terms": len(self.terms.relevant()) if self.terms else 0,
            "glossary_terms_used": sum(1 for t in self.terms.all() if t.origin == "glossary" and t.used) if self.terms else 0,
            "passages_flagged": sum(1 for p in translatable if p.issues),
            "clean": self.clean,
            "rtl": self.rtl,
            "schema_problems": self.schema_problems,
        }

    def to_json(self) -> str:
        data = self.summary()
        if self.context:
            data["context"] = self.context.as_dict()
        if self.terms:
            data["terms"] = [{"en": t.en, "ar": t.ar, "origin": t.origin, "used": t.used} for t in self.terms.relevant()]
        data["items"] = [
            {
                "id": p.id, "in_table": p.in_table, "translatable": p.translatable,
                "source": p.source, "locked": p.locked, "placeholders": p.placeholders,
                "terms": p.terms, "target": p.target, "issues": p.issues,
            }
            for p in self.passages
        ]
        return json.dumps(data, ensure_ascii=False, indent=2)


def load_passages(pkg: DocxPackage) -> tuple[list[Passage], dict]:
    passages: list[Passage] = []
    clean_stats: dict[str, int] = {}
    for part in pkg.text_parts():
        root = pkg.xml(part)
        for k, v in clean_part(root).items():
            clean_stats[k] = clean_stats.get(k, 0) + v
        passages.extend(extract_passages(root, part))
    return passages, clean_stats


def translate_docx(
    src: str | Path,
    dst: str | Path,
    translator: Translator,
    *,
    rtl: bool = True,
    limit: int | None = None,
    progress: Progress | None = None,
    glossary: list[tuple[str, str]] | None = None,
) -> Report:
    """Translate a .docx.

    limit: translate only the first N model calls (quick tests on CPU); the rest
    stays English and is counted in the report.
    """
    started = time.perf_counter()
    pkg = DocxPackage(src)
    passages, clean_stats = load_passages(pkg)
    report = Report(str(src), str(dst), translator.name, passages, clean_stats)
    arabic = getattr(translator, "target_arabic", True)

    # 1. Fixed terms: standard glossary first (it wins), then the document context
    #    pass (summary for every prompt + key terms), then labels learned below.
    terms = TermTable()
    for en, ar in glossary or []:
        terms.add(en, ar, "glossary")
    summary = ""
    if hasattr(translator, "prepare"):
        try:
            report.context = translator.prepare(passages)
        except Exception as exc:              # translate without context rather than stop
            report.context = DocContext(error=f"context pass failed: {exc}")
        summary = report.context.summary
        for en, ar in report.context.key_terms:
            terms.add(en, ar, "context")
    report.terms = terms

    # 2. Lock numbers/dates. Identical locked texts are translated once, so
    #    identical passages always get identical Arabic.
    work = [(p, lock(p.source)) for p in passages if p.translatable]
    total = len({lk.text for _, lk in work if lk.needs_model})
    if limit is not None:
        total = min(total, limit)
    cache: dict[str, str] = {}             # locked text (passage or piece) -> model answer
    done = 0

    for p, locked in work:
        p.locked = locked.text
        p.placeholders = dict(locked.values)
        plain = strip_tags(p.source)
        p.terms = [{"en": t.en, "ar": t.ar} for t in terms.find(plain)]

        if not locked.needs_model:
            raw = locked.text
        elif locked.text in cache:
            raw = cache[locked.text]
        elif limit is not None and done >= limit:
            report.not_translated_limit += 1
            p.issues.append("not translated (limit reached)")
            continue
        else:
            t0 = time.perf_counter()
            try:
                raw = _translate_planned(translator, locked, summary, terms, report, cache)
            except Exception as exc:          # model server error: keep going, flag it
                p.issues.append(f"model error, left in English: {exc}")
                report.model_errors += 1
                continue
            cache[locked.text] = raw
            done += 1
            if progress:
                progress(done, total, p, time.perf_counter() - t0)

        p.target, issues = restore(raw, locked, arabic=arabic)
        p.issues.extend(issues)
        if arabic:
            p.issues.extend(output_problems(p.target, p.source))
            if stray_brackets(p.target):
                p.issues.append("a damaged placeholder bracket (⟦ or ⟧) was left in the text")
        p.issues.extend(apply_translation(p, p.target))

        # 3. Term consistency: a short label's first clean translation is fixed.
        if arabic and not p.issues and not p.tags and not p.placeholders:
            terms.learn(plain, p.target)

    # 4. Right-to-left.
    if rtl:
        rtl_stats: dict[str, int] = {}
        for part in pkg.text_parts():
            for k, v in apply_rtl_part(pkg.xml(part)).items():
                rtl_stats[k] = rtl_stats.get(k, 0) + v
        if pkg.has("word/styles.xml"):
            rtl_stats.update(apply_rtl_styles(pkg.xml("word/styles.xml")))
        if pkg.has("word/numbering.xml"):
            rtl_stats.update(apply_rtl_numbering(pkg.xml("word/numbering.xml")))
        report.rtl = rtl_stats

    for part in pkg.text_parts() + ["word/styles.xml", "word/numbering.xml"]:
        if pkg.has(part):
            report.schema_problems.extend(order_problems(pkg.xml(part), part))
    pkg.save(dst)
    report.seconds = time.perf_counter() - started
    return report


def _translate_planned(translator, locked: Locked, summary: str, terms: TermTable, report: Report,
                       cache: dict[str, str]) -> str:
    """Translate the pieces the model should see; keep numbering and heading tags in code."""
    out = []
    for piece in plan(locked):
        if not piece.translate:
            out.append(piece.text)
        elif piece.text in cache:             # e.g. a heading that also appears as a table label
            out.append(cache[piece.text])
        else:
            unit = sub_locked(locked, piece.text)
            unit_terms = [(t.en, t.ar) for t in terms.find(strip_tags(piece.text), count=False)]
            raw = _translate_with_retry(translator, unit, tags_in(piece.text), unit_terms, summary, report)
            cache[piece.text] = raw
            out.append(raw)
    return "".join(out)


def _translate_with_retry(translator, locked: Locked, tags: list[str], unit_terms: list[tuple[str, str]],
                          summary: str, report: Report) -> str:
    ctx = {"summary": summary, "terms": unit_terms, "examples": []}
    raw = _clean_tags(translator.translate(locked.text, ctx), tags)
    report.model_calls += 1
    problems = format_problems(raw, locked, tags)
    if not problems:
        return raw
    # One retry, telling the model exactly what it lost.
    report.retries += 1
    feedback = "Your translation has problems: " + "; ".join(problems) + "."
    retry = _clean_tags(translator.translate(locked.text, {**ctx, "feedback": feedback, "previous": raw}), tags)
    return retry if len(format_problems(retry, locked, tags)) < len(problems) else raw


def _clean_tags(raw: str, tags: list[str]) -> str:
    """Formatting tags the source never had are removed (formatting only, never content)."""
    return strip_tags(raw) if not tags else raw


def format_problems(raw: str, locked: Locked, tags: list[str]) -> list[str]:
    """Placeholder and tag problems in a model answer (before restoring)."""
    problems = []
    restored, issues = restore(raw, locked)
    problems.extend(_as_placeholder_problem(i, locked) for i in issues)
    if stray_brackets(restored):
        problems.append("a placeholder was damaged; copy each ⟦..⟧ placeholder exactly")
    problems.extend(output_problems(raw, locked.text))
    try:
        parse_tagged(raw, tags)
    except TagError as exc:
        problems.append(f"formatting tags: {exc}; keep each of {', '.join(f'<{t}>' for t in tags) or 'no tags'} exactly once")
    if not raw.strip():
        problems.append("the answer was empty")
    return problems


def _as_placeholder_problem(issue: str, locked: Locked) -> str:
    # restore() reports values ('1,234'); the model only knows the placeholder names.
    for key, value in locked.values.items():
        if f"'{value}'" in issue:
            return issue.replace(f"'{value}'", key)
    return issue


def roundtrip_docx(src: str | Path, dst: str | Path, *, clean: bool = False) -> Path:
    """Parse every text part and write it back; with clean=True also clean runs."""
    pkg = DocxPackage(src)
    for part in pkg.text_parts():
        root = pkg.xml(part)
        if clean:
            clean_part(root)
    return pkg.save(dst)
