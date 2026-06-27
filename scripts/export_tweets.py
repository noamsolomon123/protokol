"""Export harvested tweets (E:\\kn-data\\tweets\\person-*.json) to the static site as
docs/data/tweets/<id>.json per MK, plus docs/data/tweets_index.json (pid -> handle,
count). Tweets are a CANDIDATE source like interviews — always shown with a link to
the original tweet; never fabricated. Only verified-handle tweets are present (the
harvester's identity gate guarantees correct attribution).
"""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))


def main() -> int:
    out_dir = REPO / "docs" / "data" / "tweets"
    out_dir.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}
    n_mk = n_tw = 0
    for f in sorted(glob.glob(str(DATA / "tweets" / "person-*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        pid, handle = d.get("person_id"), d.get("handle")
        tweets = [
            {"date": t.get("date"), "text": t.get("text"), "url": t.get("url"),
             "likes": t.get("likes"), "retweets": t.get("retweets")}
            for t in d.get("tweets", []) if (t.get("text") or "").strip()
        ]
        if not tweets:
            continue
        (out_dir / f"{pid}.json").write_text(
            json.dumps({"person_id": pid, "handle": handle, "tweets": tweets}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        index[str(pid)] = {"handle": handle, "count": len(tweets)}
        n_mk += 1
        n_tw += len(tweets)
    (REPO / "docs" / "data" / "tweets_index.json").write_text(
        json.dumps({"schema": 1, "mks": index}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"tweets export: {n_mk} MKs, {n_tw} tweets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
