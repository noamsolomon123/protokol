"""Build docs/data/search_index.json — one compact index of every transcript segment
so the search page loads a single file instead of 46 per-MK files + flattening ~17k
segments on every page load (much faster + reliable on mobile).

Compact shape (metadata deduped via an interview index):
    {"interviews":[{pid,name,vid,url,title}, ...],
     "segments":[[interviewIndex, start, "text"], ...]}
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    interviews: list[dict] = []
    segments: list[list] = []
    for f in sorted(glob.glob(str(REPO / "docs" / "data" / "mk" / "*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for iv in d.get("interviews", []):
            idx = len(interviews)
            interviews.append({
                "pid": d.get("person_id"), "name": d.get("name"),
                "vid": iv.get("video_id"), "url": iv.get("url"), "title": iv.get("title"),
            })
            for s in iv.get("segments", []):
                text = (s.get("text") or "").strip()
                if text:
                    segments.append([idx, round(float(s.get("start", 0)), 1), text])

    out_path = REPO / "docs" / "data" / "search_index.json"
    out_path.write_text(json.dumps({"schema": 1, "interviews": interviews, "segments": segments},
                                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    mb = out_path.stat().st_size / 1e6
    print(f"search_index.json: {len(interviews)} interviews, {len(segments)} segments, {mb:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
