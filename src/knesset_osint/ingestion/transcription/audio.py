"""Audio acquisition for transcription: yt-dlp download + ffmpeg chunking.

We never rehost media — this only produces LOCAL temp audio for transcription.
Chunks are re-encoded to compact mono 16 kHz so each fits inline within the
free-tier Gemini request limit even for long interviews.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from knesset_osint.core.logging import get_logger

logger = get_logger("transcription.audio")


def download_audio(url: str, out_stem: str | Path, *, max_seconds: int | None = None) -> Path:
    """Download best audio as mp3 to ``<out_stem>.mp3`` via yt-dlp.

    ``url`` may be a normal video URL or a yt-dlp search term like
    ``ytsearch1:בנימין נתניהו ראיון``. When ``max_seconds`` is set, only the
    first N seconds are fetched (fast, low quota for proofs).
    """
    out_stem = Path(out_stem)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    args = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-x",
        "--audio-format",
        "mp3",
        "--no-playlist",
        "-o",
        str(out_stem.with_suffix(".%(ext)s")),
    ]
    if max_seconds:
        args += ["--download-sections", f"*0-{max_seconds}", "--force-keyframes-at-cuts"]
    args.append(url)
    logger.info("yt-dlp downloading audio: %s", url)
    subprocess.run(args, check=True)
    mp3 = out_stem.with_suffix(".mp3")
    if not mp3.exists():
        raise FileNotFoundError(f"yt-dlp did not produce {mp3}")
    return mp3


def probe_duration(path: str | Path) -> float:
    """Return audio duration in seconds (via ffprobe)."""
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def split_audio(path: str | Path, chunk_seconds: int, out_dir: str | Path) -> list[tuple[float, Path]]:
    """Split ``path`` into <=chunk_seconds pieces (compact mono 16 kHz mp3).

    Returns ``[(start_offset_seconds, chunk_path), ...]`` so the caller can add
    the offset to each chunk's relative timestamps when stitching.
    """
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(path)
    chunks: list[tuple[float, Path]] = []
    start = 0.0
    idx = 0
    while start < duration:
        cp = out_dir / f"chunk_{idx:03d}.mp3"
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-ss", str(start), "-t", str(chunk_seconds),
                "-i", str(path),
                "-ac", "1", "-ar", "16000", "-b:a", "48k",
                str(cp),
            ],
            check=True,
        )
        if cp.exists() and cp.stat().st_size > 0:
            chunks.append((start, cp))
        start += chunk_seconds
        idx += 1
    return chunks
