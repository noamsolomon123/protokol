"""Parallel harvest pipeline: a 3-stage producer/consumer that keeps the GPU
saturated by overlapping network I/O with transcription.

    [discovery thread] --dlq--> [N download workers] --txq--> [1 transcriber]

Why: the serial harvester does search -> download -> transcribe one video at a
time, so the GPU sits idle during every download and during the 900s search
throttle. Here discovery runs in its own thread (the quota throttle no longer
stalls anything), several downloads run in parallel (network-bound), and a
single transcriber thread owns the GPU and is fed from a buffered queue so it
never waits. Bounded queues provide backpressure (no unbounded disk growth).

The engine is I/O-agnostic: callers inject the real search/download/transcribe/
sink functions, which makes it unit-testable with fakes (no network/GPU).
"""

from __future__ import annotations

import queue
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from knesset_osint.core.logging import get_logger

logger = get_logger("ingestion.harvest_pipeline")


@dataclass
class PipelineConfig:
    download_workers: int = 3       # parallel yt-dlp downloads (network-bound)
    dl_queue_size: int = 12         # max video descriptors waiting to download
    tx_queue_size: int = 4          # downloaded files buffered ahead of the GPU
    per_mk: int = 5                 # max new videos enqueued per MK per search pass
    max_seconds: int = 75 * 60      # skip videos longer than this (don't transcribe)
    search_interval: float = 900.0  # seconds between YouTube searches (quota throttle)
    max_videos: Optional[int] = None  # stop after N transcripts (None = run forever)


def _interruptible_sleep(seconds: float, stop_event: threading.Event, sleep_fn) -> None:
    elapsed, step = 0.0, 0.5
    while elapsed < seconds and not stop_event.is_set():
        sleep_fn(min(step, seconds - elapsed))
        elapsed += step


def _put(q: "queue.Queue", item, stop_event: threading.Event) -> bool:
    """Block until the item is queued or stop is requested. Returns False on stop."""
    while not stop_event.is_set():
        try:
            q.put(item, timeout=0.3)
            return True
        except queue.Full:
            continue
    return False


def _get(q: "queue.Queue", stop_event: threading.Event):
    """Get next item, or None on timeout (so the worker can re-check stop)."""
    try:
        return q.get(timeout=0.3)
    except queue.Empty:
        return None


def run_harvest(
    *,
    roster: list[dict],
    search_fn: Callable[[dict], list[dict]],
    download_fn: Callable[[dict, Path], "tuple[Path, float]"],
    transcribe_fn: Callable[[Path], list],
    sink_fn: Callable[[dict, dict, Path, float, list], None],
    processed: "set[str]",
    cursor: int = 0,
    config: PipelineConfig | None = None,
    on_commit: Optional[Callable[[list, int, int], None]] = None,
    stop_event: Optional[threading.Event] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    workdir_factory: Optional[Callable[[], Path]] = None,
    cleanup_fn: Optional[Callable[[Path], None]] = None,
    log=logger,
) -> int:
    """Run the pipeline until stop_event is set (or max_videos reached).

    Callables:
      search_fn(mk)               -> [video descriptors]; each has "video_id".
      download_fn(video, workdir) -> (audio_path, duration_seconds); raises on fail.
      transcribe_fn(audio_path)   -> segments.
      sink_fn(video, mk, audio, duration, segments) -> None (persist the result).
      on_commit(processed_sorted, cursor, transcribed_count) -> None (persist state).

    `processed` (a set of video ids) is read/mutated under an internal lock and
    is the dedup source of truth across restarts. Returns the transcript count.
    """
    config = config or PipelineConfig()
    stop_event = stop_event or threading.Event()
    workdir_factory = workdir_factory or (lambda: Path(tempfile.mkdtemp(prefix="kn_h_")))
    cleanup_fn = cleanup_fn or (lambda p: shutil.rmtree(p, ignore_errors=True))
    n = max(1, len(roster))

    lock = threading.Lock()
    processed = set(processed)
    enqueued: set[str] = set()          # in-flight (queued/downloading) — avoid dupes
    state = {"cursor": cursor % n, "transcribed": 0}
    dlq: "queue.Queue" = queue.Queue(maxsize=config.dl_queue_size)
    txq: "queue.Queue" = queue.Queue(maxsize=config.tx_queue_size)

    def commit() -> None:
        if on_commit:
            with lock:
                on_commit(sorted(processed), state["cursor"], state["transcribed"])

    def mark_processed(vid: str) -> None:
        with lock:
            processed.add(vid)
            enqueued.discard(vid)

    def discovery() -> None:
        while not stop_event.is_set():
            with lock:
                cur = state["cursor"]
                state["cursor"] = (cur + 1) % n
            mk = roster[cur]
            try:
                vids = search_fn(mk)
            except Exception as e:  # noqa: BLE001 - one bad search shouldn't kill the loop
                log.warning("search failed for %s: %s", mk.get("name"), e)
                vids = []
            new: list[tuple[dict, dict]] = []
            with lock:
                for v in vids:
                    vid = v.get("video_id")
                    if not vid or vid in processed or vid in enqueued:
                        continue
                    enqueued.add(vid)
                    new.append((mk, v))
                    if len(new) >= config.per_mk:
                        break
            for item in new:
                if not _put(dlq, item, stop_event):
                    mark_processed(item[1]["video_id"])  # release reservation on stop
                    return
            if new:
                log.info("discovered %d new for %s", len(new), mk.get("name"))
            _interruptible_sleep(config.search_interval, stop_event, sleep_fn)

    def downloader(idx: int) -> None:
        while not stop_event.is_set():
            item = _get(dlq, stop_event)
            if item is None:
                continue
            mk, v = item
            vid = v["video_id"]
            workdir = workdir_factory()
            try:
                audio, dur = download_fn(v, workdir)
            except Exception as e:  # noqa: BLE001 - mark done so we don't loop forever
                log.warning("download failed %s: %s", vid, e)
                mark_processed(vid)
                cleanup_fn(workdir)
                commit()
                continue
            if dur > config.max_seconds:
                log.info("skip %s (%.0f min > cap)", vid, dur / 60)
                mark_processed(vid)
                cleanup_fn(workdir)
                commit()
                continue
            if not _put(txq, (mk, v, workdir, audio, dur), stop_event):
                cleanup_fn(workdir)
                return

    def transcriber() -> None:
        while not stop_event.is_set():
            item = _get(txq, stop_event)
            if item is None:
                continue
            mk, v, workdir, audio, dur = item
            vid = v["video_id"]
            try:
                segs = transcribe_fn(audio)
                sink_fn(v, mk, audio, dur, segs)
                with lock:
                    state["transcribed"] += 1
                mark_processed(vid)
                log.info("done %s (%d segs)", vid, len(segs))
            except Exception as e:  # noqa: BLE001
                log.warning("transcribe failed %s: %s", vid, e)
                mark_processed(vid)
            finally:
                cleanup_fn(workdir)
            commit()
            if config.max_videos is not None and state["transcribed"] >= config.max_videos:
                stop_event.set()
                return

    threads = [threading.Thread(target=discovery, name="discovery", daemon=True)]
    for i in range(config.download_workers):
        threads.append(threading.Thread(target=downloader, args=(i,), name=f"dl-{i}", daemon=True))
    threads.append(threading.Thread(target=transcriber, name="transcriber", daemon=True))

    for t in threads:
        t.start()
    try:
        stop_event.wait()
    except KeyboardInterrupt:
        stop_event.set()
    for t in threads:
        t.join(timeout=10)
    commit()
    return state["transcribed"]
