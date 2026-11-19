"""Test UI: upload a .docx, translate it with a local model, inspect passages, download.

    python -m fs_translator serve            # http://127.0.0.1:8000

Everything stays on this machine: the page loads no external fonts or scripts,
and the only network call is to the local Ollama server.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..config import FS_MODEL, FS_TERMS_VARIANT, OLLAMA_URL
from ..glossary import VARIANTS, load_glossary
from ..pipeline import translate_docx
from ..translators import PseudoArabicTranslator

FAKE = "pseudo-arabic"
FINISHED = ("done", "error", "cancelled")
WORK_DIR = Path("output/web")
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="FS Arabic Translator (test)")
# Serves the page's assets, e.g. the official logo saved as static/logo.svg.
app.mount("/static", StaticFiles(directory=STATIC), name="static")
# One job at a time: the model already uses every CPU core.
_executor = ThreadPoolExecutor(max_workers=1)
_jobs: dict[str, "Job"] = {}
_lock = threading.Lock()


@dataclass
class Job:
    id: str
    filename: str
    model: str
    limit: int | None
    terms: str = "gcc"
    state: str = "queued"          # queued | context | translating | writing | done | error | cancelled
    done: int = 0
    total: int = 0
    current: str = ""
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    error: str = ""
    report: dict | None = None
    output: Path | None = None
    call_seconds: list[float] = field(default_factory=list)
    cancel: bool = False

    def public(self) -> dict:
        now = time.time()
        elapsed = ((self.finished or now) - self.started) if self.started else 0
        eta = None
        if self.state == "translating" and self.call_seconds and self.total:
            avg = sum(self.call_seconds) / len(self.call_seconds)
            eta = round(avg * (self.total - self.done))
        with _lock:
            queue_pos = sum(1 for j in _jobs.values() if j.state == "queued" and j.created < self.created)
        return {
            "id": self.id, "filename": self.filename, "model": self.model, "limit": self.limit, "terms": self.terms,
            "state": self.state, "done": self.done, "total": self.total, "current": self.current,
            "elapsed": round(elapsed), "eta": eta, "error": self.error, "queue_position": queue_pos,
            "report": self.report if self.state == "done" else None,
        }

    # -- persistence: a job survives a server restart ---------------------------
    _SAVED = ("id", "filename", "model", "limit", "terms", "state", "done", "total",
              "created", "started", "finished", "error")

    def save(self) -> None:
        data = {k: getattr(self, k) for k in self._SAVED}
        data["output"] = self.output.name if self.output else None
        (WORK_DIR / self.id / "job.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, job_id: str) -> "Job | None":
        job_dir = WORK_DIR / job_id
        if not re.fullmatch(r"\w+", job_id) or not job_dir.is_dir():
            return None
        meta = job_dir / "job.json"
        if meta.exists():
            data = json.loads(meta.read_text(encoding="utf-8"))
            output = data.pop("output", None)
            job = cls(**{k: data[k] for k in cls._SAVED if k in data})
            job.output = job_dir / output if output else None
        else:
            # Jobs from before job.json existed: rebuild from the files left behind.
            outputs = [p for p in job_dir.glob("*.docx") if p.name != "input.docx"]
            if not outputs or not (job_dir / "report.json").exists():
                return None
            job = cls(job_id, outputs[0].name.replace("_AR.docx", ".docx"), "", None, state="done")
            job.output = outputs[0]
            job.created = (job_dir / "input.docx").stat().st_mtime if (job_dir / "input.docx").exists() else job_dir.stat().st_mtime
            job.finished = outputs[0].stat().st_mtime
        if job.state == "done":
            report = job_dir / "report.json"
            job.report = json.loads(report.read_text(encoding="utf-8")) if report.exists() else None
            if job.report and not job.model:
                job.model = job.report.get("translator", "").removeprefix("ollama:")
        elif job.state not in ("error", "cancelled"):
            # It was running when the server stopped; the work is lost.
            job.state = "error"
            job.error = "interrupted by a server restart; please translate the file again"
        return job


# --- pages -------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


# --- api ---------------------------------------------------------------------------

@app.get("/api/models")
def models() -> dict:
    names, error = [], ""
    try:
        tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3).json()
        names = sorted(m["name"] for m in tags.get("models", []))
    except httpx.HTTPError as exc:
        error = f"Ollama not reachable at {OLLAMA_URL} ({exc.__class__.__name__})"
    default = FS_MODEL if FS_MODEL in names else (names[0] if names else FAKE)
    return {"models": names, "fake": FAKE, "default": default, "error": error}


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...), model: str = Form(FS_MODEL), limit: str = Form(""),
                     terms: str = Form(FS_TERMS_VARIANT)) -> dict:
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(400, "Please upload a Word .docx file.")
    job_id = uuid.uuid4().hex[:10]
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    src = job_dir / "input.docx"
    src.write_bytes(await file.read())
    lim = int(limit) if limit.strip().isdigit() and int(limit) > 0 else None
    if terms not in VARIANTS:
        raise HTTPException(400, f"Unknown terminology '{terms}'.")
    job = Job(job_id, Path(file.filename).name, model, lim, terms)
    with _lock:
        _jobs[job_id] = job
    job.save()
    _executor.submit(_run, job, src, job_dir)
    return job.public()


@app.get("/api/jobs")
def list_jobs(limit: int = 12) -> list[dict]:
    """Recent translations, newest first (survives restarts: read from disk)."""
    ids = {p.name for p in WORK_DIR.iterdir() if p.is_dir()} if WORK_DIR.exists() else set()
    ids |= set(_jobs)
    out = []
    for job_id in ids:
        job = _jobs.get(job_id) or Job.load(job_id)
        if not job:
            continue
        flagged = (job.report or {}).get("passages_flagged") if job.state == "done" else None
        out.append({"id": job.id, "filename": job.filename, "model": job.model, "state": job.state,
                    "created": job.created, "flagged": flagged, "error": job.error})
    out.sort(key=lambda j: j["created"] or 0, reverse=True)
    return out[:limit]


@app.delete("/api/jobs")
def clear_jobs() -> dict:
    """Delete all finished translations (uploaded file, Arabic file, report).

    Jobs that are still waiting or running are kept."""
    ids = {p.name for p in WORK_DIR.iterdir() if p.is_dir()} if WORK_DIR.exists() else set()
    ids |= set(_jobs)
    removed, kept = 0, 0
    for job_id in ids:
        job = _jobs.get(job_id) or Job.load(job_id)
        if job and job.state not in FINISHED:
            kept += 1
            continue
        shutil.rmtree(WORK_DIR / job_id, ignore_errors=True)
        with _lock:
            _jobs.pop(job_id, None)
        removed += 1
    return {"removed": removed, "kept_running": kept}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = _get(job_id)
    if job.state in ("done", "error", "cancelled"):
        raise HTTPException(409, "The job has already finished.")
    job.cancel = True
    if job.state == "queued":
        job.state = "cancelled"
        job.save()
    return job.public()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return _get(job_id).public()


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str):
    job = _get(job_id)
    if job.state != "done" or not job.output or not job.output.exists():
        raise HTTPException(409, "The translation is not finished.")
    return FileResponse(
        job.output,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=job.output.name,
    )


def _get(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if not job:
        job = Job.load(job_id)              # finished before a server restart
        if not job:
            raise HTTPException(404, "Unknown job.")
        with _lock:
            _jobs[job_id] = job
    return job


# --- worker ------------------------------------------------------------------------

class _Cancelled(Exception):
    pass


def _run(job: Job, src: Path, job_dir: Path) -> None:
    if job.cancel:                       # cancelled while waiting in the queue
        return
    job.started = time.time()
    job.save()
    stem = re.sub(r"[^\w\- ]+", "_", Path(job.filename).stem).strip() or "document"
    dst = job_dir / f"{stem}_AR.docx"
    try:
        if job.model == FAKE:
            translator = PseudoArabicTranslator()
            job.state = "translating"
        else:
            from ..llm import OllamaClient
            from ..translators.llm import LLMTranslator
            client = OllamaClient(job.model)
            client.check()
            translator = LLMTranslator(client)
            job.state = "context"

        def progress(done, total, passage, seconds):
            if job.cancel:
                raise _Cancelled()
            job.state = "translating"
            job.done, job.total = done, total
            job.current = passage.source
            job.call_seconds.append(seconds)
            if done == total:
                job.state = "writing"

        report = translate_docx(src, dst, translator, limit=job.limit, progress=progress,
                                glossary=load_glossary(job.terms))
        job.report = json.loads(report.to_json())
        (job_dir / "report.json").write_text(report.to_json(), encoding="utf-8")
        job.output = dst
        job.state = "done"
    except _Cancelled:
        job.state = "cancelled"
        job.error = "cancelled by the user"
    except Exception as exc:  # shown in the UI; the traceback goes to the server log
        traceback.print_exc()
        job.error = str(exc) or exc.__class__.__name__
        job.state = "error"
    finally:
        job.finished = time.time()
        job.save()
