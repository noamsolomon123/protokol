"""Pure tests (no network): Gemini key loading/rotation + segment parsing."""

from __future__ import annotations

import pytest

from knesset_osint.ingestion.transcription.gemini import GeminiTranscriber
from knesset_osint.ingestion.transcription.keys import GeminiKeyPool, load_gemini_keys


def test_load_gemini_keys_dedupes_and_skips_blank() -> None:
    env = {
        "GEMINI_API_KEY": "k1",
        "GEMINI_API_KEY_2": "k2",
        "GEMINI_API_KEY_3": "   ",  # blank -> skipped
        "GEMINI_API_KEY_4": "k1",   # duplicate -> skipped
    }
    assert load_gemini_keys(env) == ["k1", "k2"]


def test_key_pool_round_robins_and_wraps() -> None:
    pool = GeminiKeyPool(["a", "b", "c"])
    assert pool.current == "a"
    assert pool.advance() == "b"
    assert pool.advance() == "c"
    assert pool.advance() == "a"  # wraps
    assert len(pool) == 3


def test_key_pool_requires_at_least_one_key() -> None:
    with pytest.raises(ValueError):
        GeminiKeyPool([])


def test_masked_never_reveals_full_key() -> None:
    pool = GeminiKeyPool(["AQ.SuperSecretValue1234"])
    masked = pool.masked()[0]
    assert "SuperSecret" not in masked
    assert masked.startswith("AQ.Sup")


def test_parse_segments_plain_json() -> None:
    txt = '[{"start":0,"end":2.5,"text":"שלום"},{"start":2.5,"end":4,"text":"עולם"}]'
    segs = GeminiTranscriber._parse_segments(txt)
    assert [s.text for s in segs] == ["שלום", "עולם"]
    assert segs[0].start == 0.0 and segs[1].end == 4.0


def test_parse_segments_strips_code_fence_and_skips_bad_rows() -> None:
    txt = '```json\n[{"start":0,"end":1,"text":"א"},{"bad":1},{"start":1,"end":2,"text":"ב"}]\n```'
    segs = GeminiTranscriber._parse_segments(txt)
    assert [s.text for s in segs] == ["א", "ב"]
