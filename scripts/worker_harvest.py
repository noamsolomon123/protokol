"""24/7 interview harvester (runs forever; Ctrl-C to stop).

    discover (YouTube) -> download (yt-dlp) -> transcribe (local Whisper GPU)
    -> store timestamped Hebrew transcripts under E:\\kn-data\\transcripts\\.

Round-robins the 120 MKs, throttled to stay within the YouTube free quota,
resumable via a state file. Local Whisper transcription is free/unlimited, so
the GPU is the workhorse; we store only transcript TEXT (never rehost media).

Run (background, dedicated PC):
    .venv\\Scripts\\python.exe scripts/worker_harvest.py
Test a single MK then exit:
    .venv\\Scripts\\python.exe scripts/worker_harvest.py --once --per-mk 1 --max-minutes 20
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from knesset_osint.core.console import enable_utf8_console
from knesset_osint.core.logging import configure_logging, get_logger
from knesset_osint.ingestion.discovery import search_mk_videos
from knesset_osint.ingestion.transcription.audio import download_audio, probe_duration
from knesset_osint.ingestion.transcription.keys import load_env_file

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))
logger = get_logger("worker.harvest")


def _load_state(p: Path) -> dict:
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"processed": [], "cursor": 0, "transcribed_count": 0}


def _save_state(p: Path, s: dict) -> None:
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    enable_utf8_console()
    configure_logging("INFO")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="process one MK then exit (testing)")
    ap.add_argument("--search-interval", type=int, default=900,
                    help="seconds to wait between YouTube searches (quota throttle)")
    ap.add_argument("--per-mk", type=int, default=3, help="max new videos per MK per pass")
    ap.add_argument("--max-minutes", type=int, default=90, help="skip videos longer than this")
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

    print(f"Harvester: {len(roster)} MKs, {len(processed)} videos already done. Loading local Whisper…")
    # Imported here so a missing GPU/model only affects the worker, not imports.
    from knesset_osint.ingestion.transcription.local_whisper import LocalWhisperTranscriber

    transcriber = LocalWhisperTranscriber()
    print(f"Engine: {transcriber.model_name} on {transcriber.device}/{transcriber.compute_type}")

    stop = {"v": False}
    signal.signal(signal.SIGINT, lambda *_a: stop.__setitem__("v", True))

    while not stop["v"]:
        cursor = state.get("cursor", 0) % len(roster)
        mk = roster[cursor]
        state["cursor"] = (cursor + 1) % len(roster)
        name, pid = mk.get("name"), mk.get("person_id")

        try:
            vids = search_mk_videos(yt_key, name, max_results=args.per_mk + 3)
        except Exception as e:  # noqa: BLE001
            logger.warning("YouTube search failed for %s: %s", name, e)
            vids = []
        new = [v for v in vids if v["video_id"] not in processed][: args.per_mk]
        logger.info("MK %s (id=%s): %d candidates, %d new", name, pid, len(vids), len(new))

        for v in new:
            if stop["v"]:
                break
            vid = v["video_id"]
            url = f"https://www.youtube.com/watch?v={vid}"
            work = Path(tempfile.mkdtemp(prefix="kn_h_"))
            try:
                mp3 = download_audio(url, work / "a", max_seconds=None)
                dur = probe_duration(mp3)
                if dur > args.max_minutes * 60:
                    logger.info("skip %s (%.0f min > cap)", vid, dur / 60)
                    processed.add(vid)
                    continue
                segs = transcriber.transcribe_file(mp3)
                out_dir = DATA / "transcripts" / f"person-{pid}"
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"{vid}.json").write_text(
                    json.dumps(
                        {
                            "video_id": vid, "url": url, "title": v["title"],
                            "channel": v["channel"], "published_at": v["published_at"],
                            "person_id": pid, "mk_name": name, "duration_sec": round(dur, 1),
                            "engine": transcriber.model_name,
                            "transcribed_at": datetime.now(timezone.utc).isoformat(),
                            "segments": [
                                {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text}
                                for s in segs
                            ],
                        },
                        ensure_ascii=False, indent=2,
                    ),
                    encoding="utf-8",
                )
                processed.add(vid)
                state["transcribed_count"] = state.get("transcribed_count", 0) + 1
                logger.info("✓ %s (%.0f min, %d segs) -> person-%s", vid, dur / 60, len(segs), pid)
            except Exception as e:  # noqa: BLE001
                logger.warning("failed %s: %s", vid, e)
                processed.add(vid)  # mark attempted so we don't loop on it forever
            finally:
                shutil.rmtree(work, ignore_errors=True)

        state["processed"] = sorted(processed)
        _save_state(state_path, state)

        if args.once:
            break
        # Quota throttle between searches (interruptible).
        for _ in range(args.search_interval):
            if stop["v"]:
                break
            time.sleep(1)

    print(f"Stopped. Transcribed total: {state.get('transcribed_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
