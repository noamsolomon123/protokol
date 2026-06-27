"""F1 (targeted) — record the strict adjudication of the scanner's ranking-claim
candidates so we don't re-pay an agent to re-judge the same quotes.

The cheap scanner (scan_superlative_claims.py) pre-filters ranking/superlative claims;
an independent strict fact-check agent then adjudicates each against the verified-stats
catalog. A claim becomes a published finding ONLY if a catalog stat DIRECTLY measures
the exact asserted quantity AND conflicts with it (consensus + PM-review gate). This
script merges an agent-adjudication JSON into the candidate-adjudications ledger and
prints the publishable count (contradicted-and-confirmed only).

    python scripts/run_candidate_factcheck.py <agent_adjudications.json>

The ledger lives at E:\\kn-data\\findings\\candidate_adjudications.json. Idempotent by
(mk_name, claim). Publishing of any 'contradicted' verdict still goes through the strict
agent merge + PM review console — this script never publishes on its own.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))
LEDGER = DATA / "findings" / "candidate_adjudications.json"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_candidate_factcheck.py <agent_adjudications.json>")
        return 1
    new = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if isinstance(new, dict):
        new = new.get("adjudications", new.get("result", []))

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else []
    seen = {(x.get("mk_name"), x.get("claim")) for x in existing}
    added = 0
    for a in new:
        key = (a.get("mk_name"), a.get("claim"))
        if key not in seen:
            existing.append(a)
            seen.add(key)
            added += 1
    LEDGER.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    contradicted = [a for a in existing if a.get("verdict") == "contradicted"]
    consistent = sum(1 for a in existing if a.get("verdict") == "consistent")
    unverifiable = sum(1 for a in existing if a.get("verdict") == "unverifiable")
    print(f"ledger: {len(existing)} adjudications (+{added}); "
          f"contradicted={len(contradicted)}, consistent={consistent}, unverifiable={unverifiable}")
    if contradicted:
        print("CONTRADICTED candidates (need adversarial verify + PM review before any publish):")
        for a in contradicted:
            print(f"  - {a.get('mk_name')}: {a.get('claim')} [{a.get('metric_used')}]")
    else:
        print("No contradicted candidates — nothing to publish (integrity-correct low yield).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
