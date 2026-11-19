# FS Arabic Translator (local LLM)

## Install and run

Needs Python 3.11+ and [Ollama](https://ollama.com/download). In a terminal in the project folder:

```bash
# install (once)
pip install -r requirements.txt
ollama pull iKhalid/allam:7b

# run, then open http://127.0.0.1:8000
python -m fs_translator serve
```
# to terminate  
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess

Translates English financial statements (.docx) into Arabic .docx, keeping the layout and
setting it right to left. Runs fully on-premises: no text leaves the machine.

Status:
- **Step 1 done**: Word round trip, cleaning, segmentation, write-back and RTL.
- **Step 2 done**: amounts, percentages, years, note references and dates are locked as
  `⟦N1⟧` / `⟦D1⟧` before the model sees the text and restored after; dates come back in
  Arabic (31 ديسمبر 2025). A missing, repeated or altered figure is flagged, never fixed silently.
- **Step 3 done**: local model via Ollama (`iKhalid/allam:7b` default since the dummy-FS test, `--model` / `FS_MODEL` to swap),
  document context pass, fixed terms, one automatic retry for lost placeholders/tags.
- Test UI (`serve`). Next: step 4 checks + review screen.

## Test UI

```bash
python -m fs_translator serve        # then open http://127.0.0.1:8000
```

Upload a .docx, pick a local model (or the pseudo-Arabic layout test), optionally limit the
number of passages, watch progress, inspect every passage side by side with flags and fixed
terms, and download the Arabic .docx. Runs on this machine only; loads nothing from the internet.
Jobs are kept under `output/web/<job id>/` (input, Arabic .docx, report.json).

## Standard IFRS terminology

[glossary/ifrs_terms_en_ar.csv](glossary/ifrs_terms_en_ar.csv): about 250 English to Arabic terms
(statements, assets, liabilities, equity, profit or loss, cash flows, auditor's report, concepts,
governance, legal forms, places, currencies). Column `ar` is GCC usage (UAE, Bahrain, Kuwait,
Qatar, Oman), `ar_ksa` the Saudi (SOCPA) form where it differs. `status=review` marks terms with
regional variation or less certainty. **Draft: to be reviewed by a qualified Arabic-speaking
accountant**; edit the CSV directly (opens in Excel). Glossary terms win over terms the model
proposes. Choose with `--terms gcc|ksa|none` or in the UI.

## Command line

```bash
python -m fs_translator translate IN.docx output/ar.docx [--model iKhalid/allam:7b] [--limit 20]
python -m fs_translator context IN.docx                       # only the document context pass
python tests/make_sample.py samples/sample_fs.docx           # build a small sample FS
python -m fs_translator extract samples/sample_fs.docx        # passages that would be translated
python -m fs_translator roundtrip IN.docx output/rt.docx      # read + write back, no changes
python -m fs_translator fake IN.docx output/ar.docx           # pseudo-Arabic + RTL (+ .report.json)
powershell -ExecutionPolicy Bypass -File tools/check_in_word.ps1 output/ar.docx   # confirm Word opens it
```

Tests (standard library only):

```bash
PYTHONPATH=".:tests" python -m unittest discover -s tests -v
```

## Layout

| Module | Job |
|---|---|
| `package.py` | open the .docx zip; re-serialise only parts that were touched, copy the rest byte for byte |
| `clean.py` | drop `proofErr`, `lastRenderedPageBreak`, `rsid*`; merge runs with identical formatting |
| `segment.py` | paragraphs → passages (split at tab/break/field/symbol/note reference); inline tags `<b1>…</b1>`, links `<a1>…</a1>` |
| `textrules.py` | skip number-only / dash / currency-code passages |
| `glossary.py` | load the standard terminology (GCC or Saudi variant) |
| `checks.py` | foreign scripts, English left, damaged placeholders; clean-Arabic rule for terms |
| `placeholders.py` | lock numbers and dates as `⟦N1⟧`/`⟦D1⟧`; restore and report anything missing or duplicated |
| `writeback.py` | put the translation back into the original runs; rebuild + flag when tags are reordered or broken |
| `rtl.py` | `bidi`, `rtl`, complex-script font and `bCs/iCs/szCs`, `bidiVisual`, frames, numbering formats |
| `ooxml.py` / `validate.py` | schema-ordered insertion and an order checker (Word rejects out-of-order properties) |
| `translators/` | the `translate(text, context) -> str` interface; fake translators for now |
| `pipeline.py` | read → clean → segment → translate (dedup) → write back → RTL → check → save |
