"""Export per-MK interview data (harvested transcripts on E:) into the static site.

Reads E:\\kn-data\\transcripts\\person-<id>\\*.json (produced by the harvester)
and the real roster, then writes:
  docs/data/mk_index.json       — [{person_id, name, party, interview_count}]
  docs/data/mk/<person_id>.json — {name, party, interviews:[{...,segments}]}

Re-runnable any time to refresh the site with the latest transcripts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))
TX = DATA / "transcripts"
OUT = REPO / "docs" / "data"


def main() -> int:
    roster = json.loads((OUT / "mk_roster.json").read_text(encoding="utf-8"))
    mk_dir = OUT / "mk"
    mk_dir.mkdir(parents=True, exist_ok=True)

    index = []
    with_content = 0
    for r in roster:
        pid = r["person_id"]
        pdir = TX / f"person-{pid}"
        interviews = []
        if pdir.exists():
            for f in sorted(pdir.glob("*.json")):
                try:
                    interviews.append(json.loads(f.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    continue
        interviews.sort(key=lambda d: d.get("published_at") or "", reverse=True)
        index.append(
            {
                "person_id": pid,
                "name": r["name"],
                "party": r.get("party", ""),
                "interview_count": len(interviews),
                "segment_count": sum(len(d.get("segments", [])) for d in interviews),
            }
        )
        if interviews:
            with_content += 1
            (mk_dir / f"{pid}.json").write_text(
                json.dumps(
                    {"person_id": pid, "name": r["name"], "party": r.get("party", ""), "interviews": interviews},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

    index.sort(key=lambda x: (-x["interview_count"], x["name"]))
    (OUT / "mk_index.json").write_text(
        json.dumps({"schema": 1, "count": len(index), "with_interviews": with_content, "mks": index},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    total_iv = sum(x["interview_count"] for x in index)
    print(f"mk_index.json written: {len(index)} MKs, {with_content} with interviews, {total_iv} interviews total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
