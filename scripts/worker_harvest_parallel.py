"""24/7 PARALLEL interview harvester — overlaps download and transcription so the
GPU never sits idle (drop-in replacement for worker_harvest.py, ~2-5x faster).

    [discovery] --> [N parallel yt-dlp downloads] --> [1 batched-GPU transcriber]

Shares the same state file (E:\\kn-data\\state\\harvest_state.json) and output
layout as the serial harvester, so it picks up exactly where that left off.
Stop the serial harvester before running this — both want the GPU.

Run (background, dedicated PC):
    .venv\\Scripts\\python.exe scripts/worker_harvest_parallel.py
Standalone test (download+transcribe 2 videos then exit):
    .venv\\Scripts\\python.exe scripts/worker_harvest_parallel.py --max-videos 2 --search-interval 5
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path

from knesset_osint.core.console import enable_utf8_console
from knesset_osint.core.logging import configure_logging, get_logger
from knesset_osint.ingestion.discovery import search_mk_videos
from knesset_osint.ingestion.harvest_pipeline import PipelineConfig, run_harvest
from knesset_osint.ingestion.transcription.audio import download_audio, probe_duration
from knesset_osint.ingestion.transcription.keys import load_env_file

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))
logger = get_logger("worker.harvest_parallel")


def _load_state(p: Path) -> dict:
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"processed": [], "cursor": 0, "transcribed_count": 0}


def main() -> int:
    enable_utf8_console()
    configure_logging("INFO")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--download-workers", type=int, default=3, help="parallel yt-dlp downloads")
    ap.add_argument("--batch-size", type=int, default=8, help="GPU transcription batch size (>1 = batched)")
    ap.add_argument("--queue-ahead", type=int, default=4, help="downloaded files buffered ahead of the GPU")
    ap.add_argument("--search-interval", type=int, default=900, help="seconds between YouTube searches (quota)")
    ap.add_argument("--per-mk", type=int, default=5, help="max new videos per MK per search pass")
    ap.add_argument("--max-minutes", type=int, default=75, help="skip videos longer than this")
    ap.add_argument("--max-videos", type=int, default=None, help="stop after N transcripts (testing)")
    args = ap.parse_args()

    os.environ.setdefault("HF_HOME", str(DATA / "models"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    for k, v in load_env_file(REPO / ".env").items():
        os.environ.setdefault(k, v)
    yt_key = os.environ.get("YOUTUBE_API_KEY")
    if not yt_key:
        print("No YOUTUBE_API_KEY in .env — cannot discover videos.")
        return 1

    roster = json.loads((REPO / "docs" / "data" / "mk_roster.json").read_text(encoding="utf-8"))
    state_path = DATA / "state" / "harvest_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = _load_state(state_path)
    processed = set(state.get("processed", []))
    base_count = state.get("transcribed_count", 0)

    print(f"Parallel harvester: {len(roster)} MKs, {len(processed)} done, "
          f"{args.download_workers} downloaders. Loading batched Whisper…")
    from knesset_osint.ingestion.transcription.local_whisper import LocalWhisperTranscriber

    transcriber = LocalWhisperTranscriber(batch_size=args.batch_size)
    print(f"Engine: {transcriber.model_name} on {transcriber.device}/{transcriber.compute_type} "
          f"(batch={transcriber.batch_size}, batched={transcriber._batched is not None})")

    def search_fn(mk: dict) -> list[dict]:
        return search_mk_videos(yt_key, mk.get("name"), max_results=25)

    def download_fn(v: dict, workdir: Path):
        url = f"https://www.youtube.com/watch?v={v['video_id']}"
        audio = download_audio(url, workdir / "a", max_seconds=None)
        return audio, probe_duration(audio)

    def sink_fn(v: dict, mk: dict, audio: Path, dur: float, segs: list) -> None:
        pid = mk.get("person_id")
        out_dir = DATA / "transcripts" / f"person-{pid}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{v['video_id']}.json").write_text(
            json.dumps(
                {
                    "video_id": v["video_id"],
                    "url": f"https://www.youtube.com/watch?v={v['video_id']}",
                    "title": v.get("title"), "channel": v.get("channel"),
                    "published_at": v.get("published_at"),
                    "person_id": pid, "mk_name": mk.get("name"), "duration_sec": round(dur, 1),
                    "engine": transcriber.model_name,
                    "transcribed_at": datetime.now(timezone.utc).isoformat(),
                    "segments": [
                        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text} for s in segs
                    ],
                },
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    def on_commit(processed_sorted: list, cursor: int, transcribed_this_run: int) -> None:
        state["processed"] = processed_sorted
        state["cursor"] = cursor
        state["transcribed_count"] = base_count + transcribed_this_run
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda *_a: stop_event.set())

    config = PipelineConfig(
        download_workers=args.download_workers,
        tx_queue_size=args.queue_ahead,
        per_mk=args.per_mk,
        max_seconds=args.max_minutes * 60,
        search_interval=args.search_interval,
        max_videos=args.max_videos,
    )
    done = run_harvest(
        roster=roster, search_fn=search_fn, download_fn=download_fn,
        transcribe_fn=transcriber.transcribe_file, sink_fn=sink_fn,
        processed=processed, cursor=state.get("cursor", 0), config=config,
        on_commit=on_commit, stop_event=stop_event,
    )
    print(f"Stopped. Transcribed this run: {done}. Total: {base_count + done}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
