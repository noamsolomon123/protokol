"""Interview transcription: download audio (yt-dlp) -> chunk (ffmpeg) -> Gemini.

The Gemini transcriber rotates across the free-tier key pool to ~triple the
free quota and fails over on rate limits. Audio is chunked so long interviews
fit inline within free-tier request limits. We store only transcript TEXT +
timestamps — never the rehosted media.
"""

from knesset_osint.ingestion.transcription.keys import (
    GeminiKeyPool,
    load_env_file,
    load_gemini_keys,
)
from knesset_osint.ingestion.transcription.gemini import GeminiTranscriber, Segment
from knesset_osint.ingestion.transcription.local_whisper import LocalWhisperTranscriber

__all__ = [
    "GeminiKeyPool",
    "load_env_file",
    "load_gemini_keys",
    "GeminiTranscriber",
    "LocalWhisperTranscriber",
    "Segment",
]
