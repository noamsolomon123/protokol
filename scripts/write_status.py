"""Write docs/data/status.json — the live feed for the mission-control board
(docs/control.html). Aggregates harvester throughput, corpus + findings counts,
and roadmap F1-F10 progress. The autonomous loop runs this every tick.
"""

from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))


def _harvester() -> dict:
    out = {"transcribed": 0, "processed": 0, "active": False, "last_log_min": None}
    state = DATA / "state" / "harvest_state.json"
    if state.exists():
        try:
            s = json.loads(state.read_text(encoding="utf-8"))
            out["transcribed"] = s.get("transcribed_count", 0)
            out["processed"] = len(s.get("processed", []))
        except Exception:  # noqa: BLE001
            pass
    log = DATA / "logs" / "harvest.log"
    if log.exists():
        age = datetime.now(timezone.utc).timestamp() - log.stat().st_mtime
        out["last_log_min"] = round(age / 60, 1)
        out["active"] = age < 600  # log touched in the last 10 minutes
    return out


def _backlog() -> list[dict]:
    md = REPO / "docs" / "superpowers" / "specs" / "2026-06-27-protokol-master-roadmap.md"
    items: list[dict] = []
    if md.exists():
        for m in re.finditer(r"- \[( |x)\] \*\*(F\d+)[^\n]*", md.read_text(encoding="utf-8")):
            label = m.group(0)[6:].strip().strip("*").replace("·", "—")
            items.append({"id": m.group(2), "done": m.group(1) == "x", "label": label[:90]})
    return items


def main() -> int:
    files = glob.glob(str(DATA / "transcripts" / "person-*" / "*.json"))
    mks = {os.path.basename(os.path.dirname(f)) for f in files}
    findings = {}
    fp = REPO / "docs" / "data" / "findings.json"
    if fp.exists():
        try:
            findings = json.loads(fp.read_text(encoding="utf-8")).get("counts", {})
        except Exception:  # noqa: BLE001
            pass
    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "harvester": _harvester(),
        "corpus": {"transcripts": len(files), "mks_with_interviews": len(mks)},
        "findings": findings,
        "backlog": _backlog(),
        "agents": [
            "etl-agent", "backend-agent", "frontend-agent", "factcheck-agent",
            "research-agent", "qa-agent", "devops-agent", "efficiency-optimizer",
        ],
    }
    (REPO / "docs" / "data" / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    done = sum(1 for b in status["backlog"] if b["done"])
    print(f"status.json: {len(files)} transcripts, harvester active={status['harvester']['active']}, "
          f"backlog {done}/{len(status['backlog'])} done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
