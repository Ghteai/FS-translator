"""Settings, overridable with environment variables (no code change to swap models)."""
import os
from pathlib import Path

# Local model served by Ollama; swap via FS_MODEL or --model.
# ALLaM 7B (Arabic-first) replaced qwen2.5:7b after the Dummy_FS_2025_first5 test:
# qwen leaked Chinese/Korean into 6-15% of passages and mistranslated core terms.
FS_MODEL = os.environ.get("FS_MODEL", "iKhalid/allam:7b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

# Standard IFRS terminology and which regional variant to use (gcc | ksa | none).
FS_GLOSSARY = os.environ.get(
    "FS_GLOSSARY", str(Path(__file__).resolve().parents[1] / "glossary" / "ifrs_terms_en_ar.csv"))
FS_TERMS_VARIANT = os.environ.get("FS_TERMS_VARIANT", "gcc")

# Font for Arabic (complex-script) text written into the .docx.
CS_FONT = os.environ.get("FS_CS_FONT", "Arial")
