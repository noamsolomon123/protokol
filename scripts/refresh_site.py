"""Run all site-data exporters in order — one command for the autonomous loop so the
public site (interviews, leaderboard, minister trends, search index, status board)
stays in sync with the latest harvested transcripts and findings.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STEPS = [
    "export_site_mk.py",
    "export_leaderboard_from_findings.py",
    "build_minister_trends.py",
    "build_search_index.py",
    "write_status.py",
]


def main() -> int:
    for s in STEPS:
        r = subprocess.run([sys.executable, str(REPO / "scripts" / s)], capture_output=True, text=True)
        out = (r.stdout or r.stderr).strip()
        last = out.splitlines()[-1] if out else "(ok)"
        print(f"{s}: {last}")
        if r.returncode != 0:
            print(f"  FAILED: {(r.stderr or '')[-200:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
