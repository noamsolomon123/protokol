"""Transcribe a real interview end-to-end and prove the Gemini pipeline.

    yt-dlp download  ->  ffmpeg chunk  ->  Gemini (rotating 3 free-tier keys)
    ->  stitched, timestamped Hebrew transcript (JSON).

Usage (from repo root, with the venv):
    .venv\\Scripts\\python.exe scripts/transcribe_interview.py "<youtube-url>" --max-seconds 180
    .venv\\Scripts\\python.exe scripts/transcribe_interview.py "ytsearch1:בנימין נתניהו ראיון"

Keys are read from the git-ignored .env. The transcript is written to the
git-ignored _transcripts/ folder (we never commit transcripts of third-party
media; production storage is the database).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from knesset_osint.core.console import enable_utf8_console
from knesset_osint.core.logging import configure_logging, get_logger
from knesset_osint.ingestion.transcription.audio import download_audio, probe_duration, split_audio
from knesset_osint.ingestion.transcription.gemini import GeminiTranscriber
from knesset_osint.ingestion.transcription.keys import (
    GeminiKeyPool,
    load_env_file,
    load_gemini_keys,
)

logger = get_logger("transcribe_interview")
REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    enable_utf8_console()
    configure_logging("INFO")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", help="video URL or yt-dlp search term (ytsearch1:...)")
    ap.add_argument("--max-seconds", type=int, default=180, help="cap download length (0 = full)")
    ap.add_argument("--chunk-seconds", type=int, default=300)
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--engine", choices=["gemini", "local"], default="gemini",
                    help="gemini (cloud, 3-key rotation) | local (faster-whisper on this PC)")
    ap.add_argument("--local-model", default="ivrit-ai/whisper-large-v3-turbo-ct2",
                    help="HF model id for --engine local (ivrit.ai Hebrew fine-tune)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.engine == "local":
        from knesset_osint.ingestion.transcription.local_whisper import LocalWhisperTranscriber
        transcriber = LocalWhisperTranscriber(model=args.local_model)
        print(f"Local engine: {transcriber.model_name} on {transcriber.device}/{transcriber.compute_type}")
    else:
        for k, v in load_env_file(REPO_ROOT / ".env").items():
            os.environ.setdefault(k, v)
        pool = GeminiKeyPool(load_gemini_keys())
        transcriber = GeminiTranscriber(pool, model=args.model)
        print(f"Gemini engine: {len(pool)} key(s) {pool.masked()}")

    work = Path(tempfile.mkdtemp(prefix="kn_tx_"))
    try:
        mp3 = download_audio(args.url, work / "audio", max_seconds=(args.max_seconds or None))
        duration = probe_duration(mp3)
        print(f"Audio: {mp3.name}  (~{duration:.0f}s)")

        chunks = split_audio(mp3, args.chunk_seconds, work / "chunks")
        print(f"Split into {len(chunks)} chunk(s) of <= {args.chunk_seconds}s")

        segments: list[dict] = []
        for offset, chunk_path in chunks:
            print(f"  transcribing chunk @ {offset:.0f}s ({chunk_path.name}) ...")
            for s in transcriber.transcribe_file(chunk_path):
                segments.append(
                    {"start": round(offset + s.start, 2), "end": round(offset + s.end, 2), "text": s.text}
                )
        segments.sort(key=lambda s: s["start"])

        out_path = Path(args.out) if args.out else (REPO_ROOT / "_transcripts" / "sample-transcript.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {"source_url": args.url, "model": args.model, "segment_count": len(segments), "segments": segments},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nWrote {out_path}  ({len(segments)} segments)")
        print("--- preview ---")
        for s in segments[:8]:
            print(f"  [{s['start']:>5.0f}s] {s['text'][:90]}")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
