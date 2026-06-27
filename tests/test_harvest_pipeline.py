"""Smoke tests for the parallel harvest pipeline (no network/GPU — fakes only).

Verifies the producer/consumer plumbing: every discovered video flows
discovery -> download -> transcribe -> sink, too-long/failed downloads are
skipped (never transcribed) but still marked processed, and the run terminates
cleanly once max_videos transcripts are produced.
"""

from __future__ import annotations

import threading
from pathlib import Path

from knesset_osint.ingestion.harvest_pipeline import PipelineConfig, run_harvest

FAST = {"sleep_fn": lambda s: __import__("time").sleep(0.002),
        "workdir_factory": lambda: Path("fakework"),
        "cleanup_fn": lambda p: None}


def _video(vid, dur=600.0, fail=False):
    return {"video_id": vid, "_dur": dur, "_fail": fail}


def _harness(roster, max_videos, *, per_mk=10, download_workers=2):
    sinked, lock = [], threading.Lock()
    committed = {}

    def search_fn(mk):
        return list(mk["videos"])

    def download_fn(v, workdir):
        if v.get("_fail"):
            raise RuntimeError("boom")
        return Path("fake.mp3"), float(v["_dur"])

    def transcribe_fn(audio):
        return ["seg"]

    def sink_fn(v, mk, audio, dur, segs):
        with lock:
            sinked.append(v["video_id"])

    def on_commit(processed_sorted, cursor, transcribed):
        committed["state"] = (list(processed_sorted), cursor, transcribed)

    stop = threading.Event()
    # Safety net: a correct run finishes in well under a second; this turns a
    # hang (regression) into a failed assertion instead of a stuck test.
    watchdog = threading.Timer(10.0, stop.set)
    watchdog.start()
    processed: set[str] = set()
    config = PipelineConfig(download_workers=download_workers, per_mk=per_mk,
                            search_interval=0.01, max_videos=max_videos)
    try:
        done = run_harvest(
            roster=roster, search_fn=search_fn, download_fn=download_fn,
            transcribe_fn=transcribe_fn, sink_fn=sink_fn, processed=processed,
            config=config, on_commit=on_commit, stop_event=stop, **FAST,
        )
    finally:
        watchdog.cancel()
    return done, sinked, committed


def test_all_videos_transcribed():
    roster = [
        {"name": "A", "videos": [_video("a1"), _video("a2")]},
        {"name": "B", "videos": [_video("b1")]},
    ]
    done, sinked, committed = _harness(roster, max_videos=3)
    assert done == 3
    assert set(sinked) == {"a1", "a2", "b1"}
    # State was persisted and records all three as processed.
    assert set(committed["state"][0]) == {"a1", "a2", "b1"}
    assert committed["state"][2] == 3


def test_too_long_video_is_skipped_not_transcribed():
    roster = [{"name": "A", "videos": [_video("ok", dur=600.0),
                                       _video("toolong", dur=10 * 3600.0)]}]
    # max_seconds default is 75 min; the 10h video must never reach transcription.
    done, sinked, _ = _harness(roster, max_videos=1)
    assert "ok" in sinked
    assert "toolong" not in sinked


def test_failed_download_is_not_transcribed():
    roster = [{"name": "A", "videos": [_video("ok"), _video("bad", fail=True)]}]
    done, sinked, _ = _harness(roster, max_videos=1)
    assert "ok" in sinked
    assert "bad" not in sinked
