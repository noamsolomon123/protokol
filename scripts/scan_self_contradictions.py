"""F4 pre-filter: per-MK self-contradiction CANDIDATES.

Scans each MK's OWN interview transcripts for two percentage claims, in DIFFERENT
videos, about the SAME covered metric, whose values differ materially. These are
*candidates for review only* — never verdicts. The same number can be a level vs a
change, a different year, or a different sub-population, so a human/agent must judge
whether it is a genuine reversal (same metric, same time frame, opposite direction)
before anything is ever shown publicly. Free (local regex, no LLM).

Writes E:\\kn-data\\findings\\self_contradiction_candidates.json.
"""

from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))

# Covered metrics: matched keyword -> canonical metric label (catalog topics).
METRICS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"גיוס|מתגייס|התגייס|אחוז.{0,6}גיוס"), "גיוס לצה״ל"),
    (re.compile(r"אבטלה|מובטל|מובטלים"), "אבטלה"),
    (re.compile(r"אינפלצי|יוקר המחיה"), "אינפלציה / יוקר מחיה"),
    (re.compile(r"עוני|מתחת לקו"), "עוני"),
    (re.compile(r"תעסוקת חרד|חרדים שעובד|חרדים שעובדים|תעסוקה.{0,6}חרד"), "תעסוקת חרדים"),
    (re.compile(r"מחירי הדיור|מחיר דירה|מחירי הדירות|הדיור עלה|הדיור ירד"), "מחירי הדיור"),
]
# Percentage value in the segment: "12%", "12.5 אחוז".
PCT = re.compile(r"(\d{1,3}(?:\.\d)?)\s*(?:%|אחוז)")
# Material difference between two percentage claims to count as a candidate pair.
MIN_ABS_DIFF = 3.0  # percentage points


def _metric_of(text: str) -> str | None:
    for pat, label in METRICS:
        if pat.search(text):
            return label
    return None


def main() -> int:
    # person_id -> metric -> list of claims
    by_person: dict[str, dict] = {}
    names: dict[str, str] = {}

    for f in glob.glob(str(DATA / "transcripts" / "person-*" / "*.json")):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        pid = str(d.get("person_id"))
        names[pid] = d.get("mk_name")
        vid = d.get("video_id")
        title = d.get("title")
        for s in d.get("segments", []):
            t = (s.get("text") or "").strip()
            if "%" not in t and "אחוז" not in t:
                continue
            metric = _metric_of(t)
            if not metric:
                continue
            m = PCT.search(t)
            if not m:
                continue
            val = float(m.group(1))
            by_person.setdefault(pid, {}).setdefault(metric, []).append({
                "value": val, "video_id": vid, "title": title,
                "start": round(s.get("start", 0)), "quote": t,
            })

    candidates: list[dict] = []
    for pid, metrics in by_person.items():
        for metric, claims in metrics.items():
            # need at least two claims from DIFFERENT videos with a material gap
            for i in range(len(claims)):
                for j in range(i + 1, len(claims)):
                    a, b = claims[i], claims[j]
                    if a["video_id"] == b["video_id"]:
                        continue
                    if abs(a["value"] - b["value"]) < MIN_ABS_DIFF:
                        continue
                    candidates.append({
                        "person_id": pid, "mk_name": names.get(pid), "metric": metric,
                        "status": "candidate", "type": "self_contradiction",
                        "a": a, "b": b,
                        "note": "מועמד לבדיקה בלבד — ייתכן הבדל בין רמה לשינוי, שנים שונות או תת-אוכלוסייה. "
                                "דורש אימות אנושי/סוכן לפני כל הצגה.",
                    })

    dst = DATA / "findings" / "self_contradiction_candidates.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    people = len({c["person_id"] for c in candidates})
    print(f"{len(candidates)} self-contradiction candidate pairs across {people} MKs -> {dst}")
    # quick top summary
    from collections import Counter
    by_metric = Counter(c["metric"] for c in candidates)
    for metric, n in by_metric.most_common():
        print(f"  {metric}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
