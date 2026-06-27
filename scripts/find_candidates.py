"""Run the fact-check over harvested transcripts -> CANDIDATE findings (for human
review, never auto-published). Caches per-transcript so each run does new ones.
Writes E:\\kn-data\\findings\\findings.json and docs/data/findings.json (site).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

from knesset_osint.core.console import enable_utf8_console
from knesset_osint.ingestion.transcription.keys import GeminiKeyPool, load_env_file, load_gemini_keys
from knesset_osint.verification import factcheck as fc

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))


def main() -> int:
    enable_utf8_console()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max", type=int, default=10, help="max transcripts to process this run")
    ap.add_argument("--engine", choices=["local", "gemini"], default="gemini",
                    help="gemini (cloud, higher quality, quota-limited) or local (Ollama, free/unlimited but weaker)")
    ap.add_argument("--local-model", default="gemma3:4b", help="Ollama model for --engine local")
    ap.add_argument("--model", default="gemini-2.5-flash", help="Gemini model for --engine gemini")
    args = ap.parse_args()

    if args.engine == "local":
        from knesset_osint.verification.ollama_llm import ollama_generate_json
        def gen(p):
            return ollama_generate_json(p, model=args.local_model)
        print(f"engine: local Ollama ({args.local_model}) — unlimited")
    else:
        from knesset_osint.verification.gemini_llm import gemini_generate_json
        for k, v in load_env_file(REPO / ".env").items():
            os.environ.setdefault(k, v)
        pool = GeminiKeyPool(load_gemini_keys())
        def gen(p):
            return gemini_generate_json(pool, p, model=args.model)
        print(f"engine: gemini ({len(pool)} keys)")
    stats = fc.load_verified_stats(REPO)

    fpath = DATA / "findings" / "findings.json"
    fpath.parent.mkdir(parents=True, exist_ok=True)
    store = json.loads(fpath.read_text(encoding="utf-8")) if fpath.exists() else {"processed": [], "findings": []}
    processed = set(store.get("processed", []))
    findings = store.get("findings", [])

    files = sorted(glob.glob(str(DATA / "transcripts" / "person-*" / "*.json")))
    todo = [f for f in files if f not in processed][: args.max]
    print(f"{len(files)} transcripts, {len(processed)} processed, doing {len(todo)} this run")

    for f in todo:
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            processed.add(f)
            continue
        try:
            new_findings = fc.build_findings_for_transcript(gen, d, stats)
        except Exception as e:  # noqa: BLE001 -> retry next run (don't mark processed)
            print("extract failed", Path(f).name, e)
            continue
        for nf in new_findings:
            findings.append(nf)
            print(f"  FINDING [{nf['outcome']}] {nf['mk_name']}: {str(nf.get('quote',''))[:60]}")
        processed.add(f)

    counts = {"total": len(findings),
              "contradicted": sum(1 for x in findings if x["outcome"] == "contradicted"),
              "consistent": sum(1 for x in findings if x["outcome"] == "consistent")}
    fpath.write_text(json.dumps({"processed": sorted(processed), "findings": findings, "counts": counts}, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPO / "docs" / "data" / "findings.json").write_text(
        json.dumps({"schema": 1, "status": "candidates_for_review", "counts": counts, "findings": findings}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"findings so far: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
