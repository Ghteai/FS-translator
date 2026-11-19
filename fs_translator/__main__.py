"""Command line.

  python -m fs_translator serve     [--port 8000]          # test UI in the browser
  python -m fs_translator translate IN.docx OUT.docx [--model qwen2.5:7b] [--limit N] [--reuse-cache]
  python -m fs_translator context   IN.docx [--model ...]
  python -m fs_translator compare   A.report.json B.report.json ...
  python -m fs_translator extract   IN.docx [--all]
  python -m fs_translator roundtrip IN.docx OUT.docx [--clean]
  python -m fs_translator fake      IN.docx OUT.docx [--no-rtl] [--identity]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import FS_MODEL, FS_TERMS_VARIANT
from .glossary import load_glossary
from .package import DocxPackage
from .pipeline import load_passages, roundtrip_docx, translate_docx
from .translators import IdentityTranslator, PseudoArabicTranslator


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="fs_translator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    tr = sub.add_parser("translate", help="translate with the local model")
    tr.add_argument("src")
    tr.add_argument("dst")
    tr.add_argument("--model", default=FS_MODEL, help=f"Ollama model (default {FS_MODEL})")
    tr.add_argument("--limit", type=int, help="translate only the first N unique passages (quick test)")
    tr.add_argument("--reuse-cache", action="store_true",
                    help="development only: reuse model answers from earlier runs (output/.llm_cache.sqlite)")
    tr.add_argument("--terms", default=FS_TERMS_VARIANT, choices=["gcc", "ksa", "none"],
                    help="standard IFRS terminology: gcc (UAE, Bahrain, ...), ksa (Saudi), none")

    cx = sub.add_parser("context", help="run only the document context pass")
    cx.add_argument("src")
    cx.add_argument("--model", default=FS_MODEL)

    ex = sub.add_parser("extract", help="print the passages that would be translated")
    ex.add_argument("src")
    ex.add_argument("--all", action="store_true", help="include non-text passages")

    rt = sub.add_parser("roundtrip", help="read and write back (no translation)")
    rt.add_argument("src")
    rt.add_argument("dst")
    rt.add_argument("--clean", action="store_true", help="also clean runs")

    fk = sub.add_parser("fake", help="fake translation (pseudo-Arabic) + RTL")
    fk.add_argument("src")
    fk.add_argument("dst")
    fk.add_argument("--no-rtl", action="store_true")
    fk.add_argument("--identity", action="store_true", help="keep English text (tests write-back only)")

    cp = sub.add_parser("compare", help="compare runs: python -m fs_translator compare a.report.json b.report.json")
    cp.add_argument("reports", nargs="+")

    sv = sub.add_parser("serve", help="start the test UI (http://127.0.0.1:8000)")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = this machine only")

    args = ap.parse_args(argv)

    if args.cmd == "compare":
        from .compare import summarise, table
        print(table([summarise(p) for p in args.reports]))
        return 0

    if args.cmd == "serve":
        import uvicorn
        print(f"FS Arabic Translator test UI: http://{args.host}:{args.port}")
        uvicorn.run("fs_translator.web.app:app", host=args.host, port=args.port, log_level="warning")
        return 0

    if args.cmd in ("translate", "context"):
        from .llm import OllamaClient, OllamaError
        from .translators.llm import LLMTranslator
        cache = "output/.llm_cache.sqlite" if getattr(args, "reuse_cache", False) else None
        client = OllamaClient(args.model, cache_path=cache)
        try:
            client.check()
        except OllamaError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        translator = LLMTranslator(client)

        if args.cmd == "context":
            passages, _ = load_passages(DocxPackage(args.src))
            ctx = translator.prepare(passages)
            print(json.dumps(ctx.as_dict(), ensure_ascii=False, indent=2))
            print(f"[{client.seconds:.1f}s]")
            return 0

        print(f"model {client.model}: reading document context ...", flush=True)
        glossary = load_glossary(args.terms)
        print(f"standard terminology: {args.terms} ({len(glossary)} terms)")
        report = translate_docx(args.src, args.dst, translator, limit=args.limit, progress=_progress, glossary=glossary)
        _write_report(report, args.dst)
        print(f"model calls {client.calls} (+{client.cached} from cache), {client.seconds:.0f}s in the model")
        return 0

    if args.cmd == "roundtrip":
        out = roundtrip_docx(args.src, args.dst, clean=args.clean)
        print(f"written {out}")
    elif args.cmd == "extract":
        passages, _ = load_passages(DocxPackage(args.src))
        for p in passages:
            if p.translatable or args.all:
                flag = "" if p.translatable else "  [skip]"
                cell = " [cell]" if p.in_table else ""
                print(f"{p.id}{cell}{flag}: {p.source}")
    elif args.cmd == "fake":
        translator = IdentityTranslator() if args.identity else PseudoArabicTranslator()
        report = translate_docx(args.src, args.dst, translator, rtl=not args.no_rtl)
        _write_report(report, args.dst)
    return 0


def _progress(done: int, total: int, p, seconds: float) -> None:
    src = p.source if len(p.source) <= 70 else p.source[:67] + "..."
    print(f"[{done}/{total}] {seconds:5.1f}s  {src}", flush=True)


def _write_report(report, dst) -> None:
    report_path = Path(dst).with_suffix(".report.json")
    report_path.write_text(report.to_json(), encoding="utf-8")
    print(json.dumps(report.summary(), ensure_ascii=False, indent=2))
    print(f"written {dst}\nreport: {report_path}")


if __name__ == "__main__":
    raise SystemExit(main())
