"""Write tools/colab_gpu_test.ipynb (run this to regenerate after editing the cells)."""
import json
from pathlib import Path

CELLS = [
    ("md", """# FS Arabic Translator: GPU model test (Colab)

**For testing only, with the dummy FS or public annual reports. Never upload client financial statements:** Colab runs on Google's servers.

What this does: installs Ollama on the Colab GPU, downloads the models you pick, translates one .docx with each model using the same pipeline as the laptop, compares the runs, and gives you a zip with the Arabic .docx files and reports.

**Before you start:** *Runtime → Change runtime type → GPU* (T4 is free; L4/A100 need Colab Pro). On the laptop, run `python tools/make_colab_zip.py` to get `output/fs_translator_colab.zip`."""),
    ("code", """# 1. Which GPU did we get?
!nvidia-smi --query-gpu=name,memory.total --format=csv"""),
    ("md", """## 2. Choose models

Sizes are the 4-bit downloads; the model must fit in GPU memory with some room to spare.

| GPU | Fits |
|---|---|
| T4 16 GB (free) | `qwen2.5:14b` (9 GB), `qwen3:14b` (9 GB), `gemma3:12b` (8 GB) |
| L4 24 GB / A100 | `qwen2.5:32b` (20 GB), `qwen3:32b` (20 GB), `gemma3:27b` (17 GB) |
| Baseline | `iKhalid/allam:7b`: the laptop's current model, for a fair comparison |

Arabic-first models on Hugging Face (Falcon-H1-Arabic, Jais 2) can be pulled as `hf.co/<user>/<repo>:<quant>` **if** a GGUF build exists and this Ollama version supports the architecture: check on huggingface.co first. Check every model's licence before any client use."""),
    ("code", """MODELS = ["iKhalid/allam:7b", "gemma3:12b", "qwen2.5:14b"]   # edit me
TERMS = "gcc"        # standard terminology: gcc | ksa | none"""),
    ("code", """# 3. Install and start Ollama on the GPU
!apt-get -qq install -y zstd pciutils > /dev/null
!curl -fsSL https://ollama.com/install.sh | sh

import os, subprocess, time, httpx
server = subprocess.Popen(["ollama", "serve"], stdout=open("/content/ollama.log", "w"),
                          stderr=subprocess.STDOUT, env=dict(os.environ, OLLAMA_KEEP_ALIVE="30m"))
for _ in range(60):
    try:
        print("Ollama", httpx.get("http://127.0.0.1:11434/api/version").json()["version"], "is running")
        break
    except Exception:
        time.sleep(1)
else:
    print(open("/content/ollama.log").read()[-2000:])"""),
    ("code", """# 4. Download the models (a few minutes each)
for m in MODELS:
    !ollama pull {m}"""),
    ("code", """# 5. Upload fs_translator_colab.zip and ONE dummy/public .docx
from google.colab import files
import zipfile, shutil

uploaded = files.upload()
for name in uploaded:
    if name.endswith(".zip"):
        zipfile.ZipFile(name).extractall("/content/app")
DOCX = next(n for n in uploaded if n.lower().endswith(".docx"))
shutil.copy(DOCX, "/content/app/" + DOCX)
print("document:", DOCX)
!pip -q install lxml httpx"""),
    ("code", """# 6. Translate with each model (progress is printed per passage)
%cd /content/app
for m in MODELS:
    tag = m.replace(":", "_").replace("/", "_")
    print("=" * 80, "\\n", m)
    !python -m fs_translator translate "{DOCX}" "output/{tag}.docx" --model "{m}" --terms {TERMS}
    !ollama ps"""),
    ("code", """# 7. Compare the runs
!python -m fs_translator compare output/*.report.json"""),
    ("md", """**Reading the table:** fewer `flagged`, `foreign_script` (Chinese etc.) and `english_left` is better. `terms_followed` is how often the fixed terms were used; it measures consistency, not correctness. The real judgement is reading the Arabic .docx files in Word."""),
    ("code", """# 8. Download the Arabic .docx files and reports
!cd /content/app && zip -q -r /content/results.zip output -x "output/.llm_cache.sqlite"
files.download("/content/results.zip")"""),
    ("md", """On the laptop: unzip `results.zip` into the project's `output/` folder, open the .docx files in Word, and run
`python -m fs_translator compare output/<run>.report.json ...` to compare with the CPU runs."""),
]


def build(path: Path) -> None:
    cells = []
    for kind, src in CELLS:
        lines = src.split("\n")
        source = [ln + "\n" for ln in lines[:-1]] + [lines[-1]]
        cell = {"cell_type": "markdown" if kind == "md" else "code", "metadata": {}, "source": source}
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
        cells.append(cell)
    nb = {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }
    path.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    out = Path(__file__).with_name("colab_gpu_test.ipynb")
    build(out)
    print(f"written {out}")
