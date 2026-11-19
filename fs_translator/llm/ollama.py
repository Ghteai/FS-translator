"""Minimal client for a local Ollama server (no data leaves the machine).

Only /api/chat is used. By default every run asks the model afresh. A cache of
model answers between runs can be switched on for development (cache_path), so
re-running the same document does not repeat slow CPU calls; it is not
translation memory and is off in the UI.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

import httpx

from ..config import FS_MODEL, OLLAMA_URL


ATTEMPTS = 3


class OllamaError(RuntimeError):
    pass


def _detail(exc: httpx.HTTPStatusError) -> str:
    try:
        return f"{exc.response.status_code} {exc.response.json().get('error', '')}".strip()
    except ValueError:
        return str(exc.response.status_code)


class OllamaClient:
    def __init__(
        self,
        model: str = FS_MODEL,
        url: str = OLLAMA_URL,
        *,
        temperature: float = 0.0,
        num_ctx: int = 4096,
        timeout: float = 600.0,
        cache_path: str | Path | None = None,
    ):
        self.model = model
        self.url = url.rstrip("/")
        self.options = {"temperature": temperature, "num_ctx": num_ctx, "seed": 7}
        self._http = httpx.Client(timeout=timeout)
        self._cache = _Cache(cache_path) if cache_path else None
        self.calls = 0
        self.cached = 0
        self.seconds = 0.0
        self.server_retries = 0

    # -- health ---------------------------------------------------------------
    def check(self) -> None:
        """Raise OllamaError with a readable message if the server or model is missing."""
        try:
            tags = self._http.get(f"{self.url}/api/tags", timeout=5).json()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama is not reachable at {self.url} ({exc}). Start it with 'ollama serve'.")
        names = {m["name"] for m in tags.get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            raise OllamaError(f"model '{self.model}' is not pulled. Available: {', '.join(sorted(names))}")

    # -- chat -----------------------------------------------------------------
    def chat(self, messages: list[dict], *, json_mode: bool = False, max_tokens: int = 1024) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {**self.options, "num_predict": max_tokens},
            "keep_alive": "30m",
        }
        if json_mode:
            payload["format"] = "json"
        if self.model.startswith("qwen3"):
            payload["think"] = False          # no hidden reasoning: faster, no stray text

        key = _key(payload)
        if self._cache:
            hit = self._cache.get(key)
            if hit is not None:
                self.cached += 1
                return hit

        start = time.perf_counter()
        for attempt in range(1, ATTEMPTS + 1):
            try:
                resp = self._http.post(f"{self.url}/api/chat", json=payload)
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                # 5xx: the runner hiccuped (seen on long CPU generations) -> try again.
                if exc.response.status_code < 500 or attempt == ATTEMPTS:
                    raise OllamaError(f"Ollama request failed: {_detail(exc)}") from exc
            except httpx.TransportError as exc:
                if attempt == ATTEMPTS:
                    raise OllamaError(f"Ollama request failed: {exc}") from exc
            self.server_retries += 1
            time.sleep(2 * attempt)
        self.seconds += time.perf_counter() - start
        self.calls += 1
        text = resp.json().get("message", {}).get("content", "")
        if self._cache:
            self._cache.put(key, text)
        return text


def _key(payload: dict) -> str:
    stable = {k: payload[k] for k in ("model", "messages", "options", "format") if k in payload}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class _Cache:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.execute("CREATE TABLE IF NOT EXISTS llm (key TEXT PRIMARY KEY, response TEXT)")

    def get(self, key: str) -> str | None:
        row = self._db.execute("SELECT response FROM llm WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, response: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO llm VALUES (?, ?)", (key, response))
        self._db.commit()
