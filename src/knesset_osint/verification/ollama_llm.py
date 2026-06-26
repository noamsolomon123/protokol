"""Local LLM via Ollama (free, unlimited, on the GPU) for claim extraction +
adjudication. Mirrors gemini_generate_json so factcheck can use either backend —
removing the Gemini free-quota bottleneck.

Local models are messier than Gemini at strict JSON, so we parse leniently:
strip ``` fences, extract the first JSON array/object, tolerate prose around it.
"""

from __future__ import annotations

import json
import re

import httpx

from knesset_osint.core.logging import get_logger

logger = get_logger("verification.ollama_llm")

_URL = "http://localhost:11434/api/generate"


def _extract_json(txt: str):
    txt = (txt or "").strip()
    if not txt:
        return None
    if "```" in txt:
        m = re.search(r"```(?:json)?\s*(.+?)```", txt, re.S)
        if m:
            txt = m.group(1).strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        pass
    m = re.search(r"(\[.*\]|\{.*\})", txt, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None


def ollama_generate_json(prompt: str, *, model: str = "gemma4:e2b", timeout: float = 300.0):
    """Generate JSON from a local Ollama model, parsed leniently."""
    body = {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.0}}
    r = httpx.post(_URL, json=body, timeout=timeout)
    r.raise_for_status()
    parsed = _extract_json(r.json().get("response"))
    return parsed if parsed is not None else []
