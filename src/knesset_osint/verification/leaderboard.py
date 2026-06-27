"""Build the public leaderboard rows from the LIVE findings pipeline.

The harvester -> find_candidates pipeline writes findings to docs/data/findings.json;
this turns them into the per-MK "contradicted official data" ranking the site shows.

INTEGRITY: transcription-sourced findings are CANDIDATES until a human reviews
them, and the public ranking must never auto-publish unreviewed verdicts — so
only findings with a PUBLISHED status (human-confirmed) are counted. The board
stays honestly empty until review; candidates still appear (labelled) on the
findings page. Wording is always "contradicted by official data", never "liar".
"""

from __future__ import annotations

from collections import Counter

# Statuses considered safe to publish in the public ranking (human-reviewed).
PUBLISHED_STATUSES = frozenset({"confirmed", "published", "reviewed"})


def build_leaderboard_rows(
    findings: list[dict],
    roster: list[dict],
    *,
    published_statuses: frozenset[str] = PUBLISHED_STATUSES,
) -> list[dict]:
    """Return [{slug, full_name, party, contradicted_count}, ...] desc by count.

    Counts only contradicted findings whose status is human-published; candidate
    findings are excluded by design. Name/party come from the roster (fallback to
    the finding's own mk_name when an id is missing from the roster).
    """
    by_id = {r.get("person_id"): r for r in roster}
    counts: Counter = Counter()
    fallback_name: dict = {}
    for f in findings:
        if f.get("outcome") != "contradicted":
            continue
        if f.get("status") not in published_statuses:
            continue
        pid = f.get("person_id")
        if pid is None:
            continue
        counts[pid] += 1
        fallback_name[pid] = f.get("mk_name")

    rows = []
    for pid, n in counts.items():
        r = by_id.get(pid, {})
        rows.append({
            "slug": f"person-{pid}",
            "full_name": r.get("name") or fallback_name.get(pid) or str(pid),
            "party": r.get("party", ""),
            "contradicted_count": int(n),
        })
    rows.sort(key=lambda x: (-x["contradicted_count"], x["slug"]))
    return rows
