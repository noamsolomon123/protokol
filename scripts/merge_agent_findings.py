"""Merge F1 multi-model fact-check workflow output into findings.json + leaderboard.

    python scripts/merge_agent_findings.py <workflow_result.json>

Agent findings carry a consensus `status`: 'confirmed' (Claude extractor + adversarial
verifier agreed) feeds the public leaderboard; everything else is a labeled candidate.
Idempotent (dedupes by person+video+quote); records processed transcripts so we don't
re-check them. Never fabricates — it only carries through stats the agents copied from
the sourced catalog.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from knesset_osint.core.console import enable_utf8_console
from knesset_osint.verification.leaderboard import build_leaderboard_rows

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))


def _counts(findings: list[dict]) -> dict:
    return {
        "total": len(findings),
        "contradicted": sum(1 for x in findings if x.get("outcome") == "contradicted"),
        "consistent": sum(1 for x in findings if x.get("outcome") == "consistent"),
        "confirmed": sum(1 for x in findings if x.get("status") == "confirmed"),
    }


def main() -> int:
    enable_utf8_console()
    if len(sys.argv) < 2:
        print("usage: merge_agent_findings.py <workflow_result.json>")
        return 1
    raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    # Workflow output files wrap the script's return value under "result".
    res = raw.get("result", raw) if isinstance(raw, dict) else raw
    new = res.get("all", [])
    processed = res.get("processed", [])

    fpath = DATA / "findings" / "findings.json"
    fpath.parent.mkdir(parents=True, exist_ok=True)
    store = json.loads(fpath.read_text(encoding="utf-8")) if fpath.exists() else {"processed": [], "findings": []}
    findings = store.get("findings", [])
    seen = {(f.get("person_id"), f.get("video_id"), f.get("quote")) for f in findings}

    added = 0
    for f in new:
        # Consensus is the gate: only findings BOTH models agreed are valid
        # (status 'confirmed') are stored. Anything the adversarial verifier
        # rejected (misattribution, normative, indirect stat) is dropped — never
        # shown, not even as a candidate. Integrity over volume.
        if f.get("status") != "confirmed":
            continue
        key = (f.get("person_id"), f.get("video_id"), f.get("quote"))
        if key in seen:
            continue
        seen.add(key)
        stat = f.get("stat", {}) or {}
        findings.append({
            "person_id": f.get("person_id"), "mk_name": f.get("mk_name"),
            "video_id": f.get("video_id"),
            "url": f"https://www.youtube.com/watch?v={f.get('video_id')}",
            "title": f.get("title"),
            "topic": f.get("topic"), "quote": f.get("quote"), "claim": f.get("claim"),
            "approx_seconds": f.get("approx_seconds"),
            "outcome": f.get("outcome"), "confidence": f.get("confidence"), "reason": f.get("reason"),
            "stat": {k: stat.get(k) for k in
                     ("metric", "dimension_value", "value", "unit", "period", "source_org", "source_url", "confirm_quote")},
            "status": f.get("status", "candidate"),
            "engine": "claude-agent-consensus",
        })
        added += 1

    # Claims-harvest: hard quantitative claims that lacked a catalog stat -> the
    # research backlog (internal). Dedupe by person+video+quote.
    sw = res.get("stats_wanted", [])
    if sw:
        swpath = DATA / "findings" / "stats_wanted.json"
        existing = json.loads(swpath.read_text(encoding="utf-8")) if swpath.exists() else []
        seen_sw = {(x.get("person_id"), x.get("video_id"), x.get("quote")) for x in existing}
        for u in sw:
            k = (u.get("person_id"), u.get("video_id"), u.get("quote"))
            if k not in seen_sw:
                existing.append(u)
                seen_sw.add(k)
        swpath.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"stats_wanted: +{len(sw)} this run, {len(existing)} total (research backlog)")

    # Record processed transcripts (agent path) so future runs skip them.
    apath = DATA / "findings" / "agent_processed.json"
    ap = set(json.loads(apath.read_text(encoding="utf-8"))) if apath.exists() else set()
    ap.update(processed)
    apath.write_text(json.dumps(sorted(ap), ensure_ascii=False, indent=2), encoding="utf-8")

    counts = _counts(findings)
    fpath.write_text(json.dumps({"processed": store.get("processed", []), "findings": findings, "counts": counts},
                                ensure_ascii=False, indent=2), encoding="utf-8")
    (REPO / "docs" / "data" / "findings.json").write_text(
        json.dumps({"schema": 1, "status": "candidates_and_confirmed", "counts": counts, "findings": findings},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    # Rebuild the public leaderboard from findings (confirmed contradictions only).
    roster = json.loads((REPO / "docs" / "data" / "mk_roster.json").read_text(encoding="utf-8"))
    rows = build_leaderboard_rows(findings, roster)
    (REPO / "docs" / "data" / "leaderboard.json").write_text(
        json.dumps({"schema_version": 1, "metric": "statements_contradicted_by_official_data", "rows": rows},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"merged +{added} findings; counts={counts}; leaderboard rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
