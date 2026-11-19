"""Package the code for a Colab GPU test: code + glossary only.

    python tools/make_colab_zip.py          -> output/fs_translator_colab.zip

Deliberately excluded: output/ (translations, reports, model cache), samples,
.docx files and anything else in the project folder. Upload the dummy/public
document separately in the notebook. Never upload client financial statements.
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ["fs_translator", "glossary", "requirements.txt"]
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".docx", ".sqlite", ".pdf"}


def build(out: Path) -> list[str]:
    out.parent.mkdir(parents=True, exist_ok=True)
    names = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in INCLUDE:
            path = ROOT / item
            files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
            for f in files:
                if SKIP_DIRS & set(f.relative_to(ROOT).parts) or f.suffix in SKIP_SUFFIXES:
                    continue
                name = f.relative_to(ROOT).as_posix()
                zf.write(f, name)
                names.append(name)
    return names


if __name__ == "__main__":
    out = ROOT / "output" / "fs_translator_colab.zip"
    names = build(out)
    print(f"written {out} ({len(names)} files, {out.stat().st_size // 1024} KB)")
