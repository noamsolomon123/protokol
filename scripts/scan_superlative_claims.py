"""Cheap pre-filter for the fact-check: scan all transcripts for SUPERLATIVE /
RANKING claims on topics the catalog actually covers ("the highest/lowest in the
country", "first/last place", "record"). These are the most likely to be hard,
falsifiable, and checkable — so we run the expensive agent fact-check only on the
strongest candidates instead of the whole corpus.

Writes E:\\kn-data\\findings\\superlative_candidates.json. Free (local regex, no LLM).
"""

from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))

# National-ranking phrasing (a claim that something is the most/least in the country).
RANK = re.compile(
    r"הכי \S+ (בארץ|במדינה|בעולם|בישראל)|הגבוה ביותר|הנמוך ביותר|הגבוהה ביותר|הנמוכה ביותר"
    r"|מקום ראשון|מקום אחרון|השיא של|ראשונה בעולם|אחרונה ב"
)
# Topics for which we have official statistics in the catalog.
TOPIC = re.compile(
    r"גיוס|מתגייס|התגייס|אבטלה|מובטל|אינפלצי|יוקר המחיה|פשיע|נרצח|רצח|עוני|מתחת לקו"
    r"|ערבים|ערביי ישראל|חרדים שעובד|תעסוקת חרד|מחירי הדיור|מחיר דירה"
)


def main() -> int:
    out: list[dict] = []
    for f in glob.glob(str(DATA / "transcripts" / "person-*" / "*.json")):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for s in d.get("segments", []):
            t = (s.get("text") or "").strip()
            if RANK.search(t) and TOPIC.search(t):
                out.append({
                    "mk_name": d.get("mk_name"), "person_id": d.get("person_id"),
                    "video_id": d.get("video_id"), "start": round(s.get("start", 0)), "quote": t,
                })
    dst = DATA / "findings" / "superlative_candidates.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(out)} ranking-claim candidates across {len({c['video_id'] for c in out})} transcripts -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
