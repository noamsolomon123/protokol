"""Write docs/data/leaderboard.json from the LIVE findings pipeline (findings.json
+ roster). The site's leaderboard reads this file. Only human-confirmed
contradictions are counted (candidates are excluded — see verification.leaderboard).

Run:
    .venv\\Scripts\\python.exe scripts/export_leaderboard_from_findings.py
"""

from __future__ import annotations

import json
from pathlib import Path

from knesset_osint.core.console import enable_utf8_console
from knesset_osint.verification.leaderboard import build_leaderboard_rows

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "docs" / "data"


def main() -> int:
    enable_utf8_console()
    findings = json.loads((DATA / "findings.json").read_text(encoding="utf-8")).get("findings", [])
    roster = json.loads((DATA / "mk_roster.json").read_text(encoding="utf-8"))
    rows = build_leaderboard_rows(findings, roster)
    (DATA / "leaderboard.json").write_text(
        json.dumps(
            {"schema_version": 1, "metric": "statements_contradicted_by_official_data", "rows": rows},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"leaderboard.json: {len(rows)} MK(s) with confirmed contradictions "
          f"(of {len(findings)} findings, candidates excluded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
