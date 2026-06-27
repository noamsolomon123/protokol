"""Merge F1 multi-model fact-check workflow output into findings.json + leaderboard,
and apply human (PM) review decisions exported from the review console (F3).

    # merge a fact-check workflow result
    python scripts/merge_agent_findings.py <workflow_result.json>

    # apply PM review decisions (affirm / retract) exported by docs/review.html
    python scripts/merge_agent_findings.py --decisions reviewed.json

Agent findings carry a consensus `status`: only 'confirmed' (Claude extractor +
adversarial verifier agreed it is a STRICT contradiction backed by a stat that
directly measures the claimed quantity) is stored and feeds the public leaderboard.

The PM-review gate (F3): a published finding can be **retracted** by the PM via the
review console. Retracted findings are dropped AND recorded in a blocklist
(retracted.json) so a later re-run of the fact-check can never republish them — this
is exactly what caught the Tur-Paz "100k not serving" false positive.

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
FPATH = DATA / "findings" / "findings.json"
RETRACTED = DATA / "findings" / "retracted.json"


def _key(f: dict) -> tuple:
    return (f.get("person_id"), f.get("video_id"), f.get("quote"))


def _counts(findings: list[dict]) -> dict:
    return {
        "total": len(findings),
        "contradicted": sum(1 for x in findings if x.get("outcome") == "contradicted"),
        "consistent": sum(1 for x in findings if x.get("outcome") == "consistent"),
        "confirmed": sum(1 for x in findings if x.get("status") == "confirmed"),
    }


def _assign_ids(findings: list[dict]) -> None:
    """Give every stored finding a stable human-friendly id (F-0001…). Existing ids
    are preserved so the console / disputes can reference them across runs."""
    mx = 0
    for f in findings:
        i = f.get("id", "")
        if isinstance(i, str) and i.startswith("F-"):
            try:
                mx = max(mx, int(i[2:]))
            except ValueError:
                pass
    for f in findings:
        if not f.get("id"):
            mx += 1
            f["id"] = f"F-{mx:04d}"


def _load_store() -> dict:
    return json.loads(FPATH.read_text(encoding="utf-8")) if FPATH.exists() else {"processed": [], "findings": []}


def _load_retracted() -> set:
    if not RETRACTED.exists():
        return set()
    return {tuple(x) for x in json.loads(RETRACTED.read_text(encoding="utf-8"))}


def _write_outputs(store: dict) -> int:
    """Write the internal store + the PUBLIC docs files. Only PM-affirmed/confirmed
    findings reach the public findings.json + leaderboard."""
    findings = store["findings"]
    _assign_ids(findings)
    counts = _counts(findings)
    FPATH.parent.mkdir(parents=True, exist_ok=True)
    FPATH.write_text(json.dumps({"processed": store.get("processed", []), "findings": findings, "counts": counts},
                                ensure_ascii=False, indent=2), encoding="utf-8")

    public = [f for f in findings if f.get("status") == "confirmed"]
    pub_counts = _counts(public)
    (REPO / "docs" / "data" / "findings.json").write_text(
        json.dumps({"schema": 1, "status": "candidates_and_confirmed", "counts": pub_counts, "findings": public},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    roster = json.loads((REPO / "docs" / "data" / "mk_roster.json").read_text(encoding="utf-8"))
    rows = build_leaderboard_rows(public, roster)
    (REPO / "docs" / "data" / "leaderboard.json").write_text(
        json.dumps({"schema_version": 1, "metric": "statements_contradicted_by_official_data", "rows": rows},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return len(rows)


def apply_decisions(path: str) -> int:
    """Apply PM review decisions exported by docs/review.html.
    {decisions:[{id, decision: 'confirm'|'reject', note}]}
    confirm -> affirm (mark pm_affirmed, keep published); reject -> retract + blocklist."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    decisions = raw.get("decisions", raw if isinstance(raw, list) else [])
    by_id = {d["id"]: d for d in decisions if d.get("id")}

    store = _load_store()
    findings = store["findings"]
    retracted = _load_retracted()

    kept, dropped, affirmed = [], 0, 0
    for f in findings:
        d = by_id.get(f.get("id"))
        if d and d.get("decision") == "reject":
            retracted.add(_key(f))
            dropped += 1
            continue
        if d and d.get("decision") == "confirm":
            f["pm_affirmed"] = True
            if d.get("note"):
                f["pm_note"] = d["note"]
            affirmed += 1
        kept.append(f)
    store["findings"] = kept

    RETRACTED.parent.mkdir(parents=True, exist_ok=True)
    RETRACTED.write_text(json.dumps(sorted(retracted), ensure_ascii=False, indent=2), encoding="utf-8")
    rows = _write_outputs(store)
    print(f"decisions applied: affirmed {affirmed}, retracted {dropped}; "
          f"blocklist={len(retracted)}; leaderboard rows={rows}")
    return 0


def merge(path: str) -> int:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    # Workflow output files wrap the script's return value under "result".
    res = raw.get("result", raw) if isinstance(raw, dict) else raw
    new = res.get("all", [])
    processed = res.get("processed", [])

    store = _load_store()
    findings = store["findings"]
    seen = {_key(f) for f in findings}
    retracted = _load_retracted()

    added = 0
    for f in new:
        # Consensus is the gate: only findings BOTH models agreed are valid
        # (status 'confirmed') are stored. Anything the adversarial verifier
        # rejected (misattribution, normative, indirect stat) is dropped — never
        # shown. Integrity over volume.
        if f.get("status") != "confirmed":
            continue
        key = _key(f)
        if key in seen:
            continue
        if key in retracted:  # PM retracted this before — never republish.
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

    rows = _write_outputs(store)
    print(f"merged +{added} findings; counts={_counts(findings)}; leaderboard rows={rows}")
    return 0


def main() -> int:
    enable_utf8_console()
    args = sys.argv[1:]
    if "--decisions" in args:
        i = args.index("--decisions")
        if i + 1 >= len(args):
            print("usage: merge_agent_findings.py --decisions <reviewed.json>")
            return 1
        return apply_decisions(args[i + 1])
    if not args:
        print("usage: merge_agent_findings.py <workflow_result.json> | --decisions <reviewed.json>")
        return 1
    return merge(args[0])


if __name__ == "__main__":
    raise SystemExit(main())
