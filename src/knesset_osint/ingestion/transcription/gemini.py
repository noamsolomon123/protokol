"""GeminiTranscriber: audio file -> timestamped Hebrew segments via Gemini.

Sends audio inline (base64) to the Gemini generateContent endpoint, rotating
across the free-tier key pool and failing over on rate limits (429/503/5xx).
Returns segments with start/end seconds RELATIVE to the audio passed in (the
caller offsets them when stitching chunks of a long interview).
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from knesset_osint.core.logging import get_logger
from knesset_osint.ingestion.transcription.keys import GeminiKeyPool

logger = get_logger("transcription.gemini")
# httpx logs the full request URL at INFO level — which includes the ?key= API
# secret. Keep it at WARNING so API keys can never land in logs/output.
logging.getLogger("httpx").setLevel(logging.WARNING)

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_PROMPT = (
    "תמלל את קטע השמע הבא לעברית במדויק, מילה במילה. "
    'החזר JSON תקין בלבד — מערך של אובייקטים בצורה '
    '{"start": שניות_התחלה, "end": שניות_סיום, "text": "הטקסט שנאמר"} '
    "לפי סדר הדיבור. הזמנים נמדדים בשניות יחסית לתחילת הקטע. "
    "אל תוסיף שום הסבר או טקסט מחוץ ל-JSON. אם אין דיבור, החזר []."
)


@dataclass
class Segment:
    start: float
    end: float
    text: str


class GeminiTranscriber:
    def __init__(
        self,
        pool: GeminiKeyPool,
        *,
        model: str = "gemini-2.5-flash",
        max_retries: int | None = None,
        timeout: float = 300.0,
    ) -> None:
        self.pool = pool
        self.model = model
        self.max_retries = max_retries if max_retries is not None else max(3, len(pool) * 3)
        self.timeout = timeout

    def transcribe_file(self, path: str | Path, *, mime: str = "audio/mp3") -> list[Segment]:
        data = Path(path).read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        body = {
            "contents": [
                {
                    "parts": [
                        {"inline_data": {"mime_type": mime, "data": b64}},
                        {"text": _PROMPT},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
        }
        text = self._post_with_rotation(body)
        return self._parse_segments(text)

    def _post_with_rotation(self, body: dict) -> str:
        url = _ENDPOINT.format(model=self.model)
        last_err: object = None
        for attempt in range(self.max_retries):
            key = self.pool.current
            try:
                r = httpx.post(url, params={"key": key}, json=body, timeout=self.timeout)
            except httpx.HTTPError as e:  # network hiccup -> rotate + retry
                last_err = e
                logger.warning("Gemini network error (attempt %d): %s", attempt + 1, e)
                self.pool.advance()
                continue
            if r.status_code == 200:
                return self._extract_text(r.json())
            if r.status_code in (429, 503) or r.status_code >= 500:
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                logger.warning(
                    "Gemini %d (rate/temporary) on attempt %d/%d — rotating key.",
                    r.status_code,
                    attempt + 1,
                    self.max_retries,
                )
                self.pool.advance()
                time.sleep(min(2 * attempt, 8))
                continue
            # 400/401/403 etc. — not retryable
            raise RuntimeError(f"Gemini error HTTP {r.status_code}: {r.text[:300]}")
        raise RuntimeError(
            f"Gemini transcription failed after {self.max_retries} attempts: {last_err}"
        )

    @staticmethod
    def _extract_text(payload: dict) -> str:
        return payload["candidates"][0]["content"]["parts"][0]["text"]

    @staticmethod
    def _parse_segments(text: str) -> list[Segment]:
        text = text.strip()
        if text.startswith("```"):
            # ```json\n[...]\n```  ->  middle block
            parts = text.split("```")
            text = parts[1] if len(parts) >= 2 else text
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
        rows = json.loads(text)
        segments: list[Segment] = []
        for r in rows:
            try:
                segments.append(
                    Segment(float(r["start"]), float(r["end"]), str(r["text"]).strip())
                )
            except (KeyError, TypeError, ValueError):
                continue  # skip malformed rows rather than fail the whole transcript
        return segments
