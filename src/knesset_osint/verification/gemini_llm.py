"""Gemini text generation with API-key-pool rotation (for claim extraction etc.).

Reuses the free-tier Gemini key pool (rotates on rate limits) — same keys as the
transcriber. Returns the model's text, or parsed JSON via gemini_generate_json.
"""

from __future__ import annotations

import json
import logging
import time

import httpx

from knesset_osint.core.logging import get_logger
from knesset_osint.ingestion.transcription.keys import GeminiKeyPool

logger = get_logger("verification.gemini_llm")
logging.getLogger("httpx").setLevel(logging.WARNING)  # never log the ?key= secret

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def gemini_generate(
    pool: GeminiKeyPool,
    prompt: str,
    *,
    model: str = "gemini-2.5-flash",
    json_out: bool = True,
    timeout: float = 120.0,
    max_retries: int | None = None,
) -> str:
    """Generate text from Gemini, rotating keys on 429/5xx. Returns raw text."""
    max_retries = max_retries if max_retries is not None else max(3, len(pool) * 3)
    body: dict = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.0}}
    if json_out:
        body["generationConfig"]["responseMimeType"] = "application/json"
    url = _ENDPOINT.format(model=model)
    last: object = None
    for attempt in range(max_retries):
        try:
            r = httpx.post(url, params={"key": pool.current}, json=body, timeout=timeout)
        except httpx.HTTPError as e:
            last = e
            pool.advance()
            continue
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if r.status_code in (429, 503) or r.status_code >= 500:
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
            logger.warning("Gemini %d (attempt %d) — rotating key.", r.status_code, attempt + 1)
            pool.advance()
            time.sleep(min(2 * attempt, 8))
            continue
        raise RuntimeError(f"Gemini error HTTP {r.status_code}: {r.text[:300]}")
    raise RuntimeError(f"Gemini generate failed after {max_retries} attempts: {last}")


def gemini_generate_json(pool: GeminiKeyPool, prompt: str, **kw):
    """Generate and parse JSON (tolerates ```json fences)."""
    txt = gemini_generate(pool, prompt, json_out=True, **kw).strip()
    if txt.startswith("```"):
        parts = txt.split("```")
        txt = parts[1] if len(parts) >= 2 else txt
        if txt.lstrip().lower().startswith("json"):
            txt = txt.lstrip()[4:]
    return json.loads(txt)
