"""PARALLEL fact-check: run the strict claim-extraction + adjudication over many
transcripts concurrently — one worker thread per Gemini key, so each key uses its
OWN free-tier rate budget (~Nx throughput vs the serial find_candidates.py).

Only Gemini is parallelised here: the free tier is quota-bound, and the binding
limit is per-key requests/minute, so K keys -> K independent request streams.
Each worker owns a pool rotated to start on its own key (still fails over to the
others on 429). Findings are CANDIDATES for human review — never auto-published.

Run (uses all configured keys):
    .venv\\Scripts\\python.exe scripts/find_candidates_parallel.py --max 24
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from knesset_osint.core.console import enable_utf8_console
from knesset_osint.ingestion.transcription.keys import GeminiKeyPool, load_env_file, load_gemini_keys
from knesset_osint.verification import factcheck as fc

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))


def _rotated(keys: list[str], offset: int) -> list[str]:
    """Keys starting at `offset` so worker i begins on key i (still fails over)."""
    if not keys:
        return keys
    i = offset % len(keys)
    return keys[i:] + keys[:i]


def main() -> int:
    enable_utf8_console()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max", type=int, default=24, help="max transcripts to process this run")
    ap.add_argument("--model", default="gemini-2.5-flash", help="Gemini model")
    ap.add_argument("--workers", type=int, default=None, help="threads (default = number of keys)")
    args = ap.parse_args()

    from knesset_osint.verification.gemini_llm import gemini_generate_json

    for k, v in load_env_file(REPO / ".env").items():
        os.environ.setdefault(k, v)
    keys = load_gemini_keys()
    workers = args.workers or len(keys)
    print(f"engine: gemini ({len(keys)} keys), {workers} parallel workers")
    stats = fc.load_verified_stats(REPO)

    fpath = DATA / "findings" / "findings.json"
    fpath.parent.mkdir(parents=True, exist_ok=True)
    store = json.loads(fpath.read_text(encoding="utf-8")) if fpath.exists() else {"processed": [], "findings": []}
    processed = set(store.get("processed", []))
    findings = store.get("findings", [])

    files = sorted(glob.glob(str(DATA / "transcripts" / "person-*" / "*.json")))
    todo = [f for f in files if f not in processed][: args.max]
    print(f"{len(files)} transcripts, {len(processed)} processed, doing {len(todo)} this run")
    if not todo:
        return 0

    # One pool per worker thread, each starting on a distinct key.
    pools = [GeminiKeyPool(_rotated(keys, i)) for i in range(workers)]
    lock = threading.Lock()
    counter = {"i": 0}

    def gen_for(pool: GeminiKeyPool):
        return lambda p: gemini_generate_json(pool, p, model=args.model)

    def work(idx_file: tuple[int, str]) -> None:
        idx, f = idx_file
        pool = pools[idx % workers]
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            with lock:
                processed.add(f)
            return
        try:
            new = fc.build_findings_for_transcript(gen_for(pool), d, stats)
        except Exception as e:  # noqa: BLE001 -> leave unprocessed, retry next run
            print("extract failed", Path(f).name, e)
            return
        with lock:
            for nf in new:
                findings.append(nf)
                print(f"  FINDING [{nf['outcome']}] {nf['mk_name']}: {str(nf.get('quote',''))[:60]}")
            processed.add(f)
            counter["i"] += 1
            if counter["i"] % 5 == 0:
                _persist(fpath, processed, findings)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, enumerate(todo)))

    _persist(fpath, processed, findings)
    counts = _counts(findings)
    print(f"findings so far: {counts}")
    return 0


def _counts(findings: list[dict]) -> dict:
    return {"total": len(findings),
            "contradicted": sum(1 for x in findings if x["outcome"] == "contradicted"),
            "consistent": sum(1 for x in findings if x["outcome"] == "consistent")}


def _persist(fpath: Path, processed: set, findings: list[dict]) -> None:
    counts = _counts(findings)
    fpath.write_text(json.dumps({"processed": sorted(processed), "findings": findings, "counts": counts},
                                ensure_ascii=False, indent=2), encoding="utf-8")
    (REPO / "docs" / "data" / "findings.json").write_text(
        json.dumps({"schema": 1, "status": "candidates_for_review", "counts": counts, "findings": findings},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
