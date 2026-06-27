"""F7 connections engine — build a SOURCED people ↔ topic ↔ official-statistic graph.

The only honest, sourced connections in this corpus: which MKs *talk about* which
covered topics (counted from their own interview transcripts), and the official
series that *measures* each topic. Correlation only — that an MK discusses a topic
says nothing about causation, and we never imply it.

For each of the catalog's official series we keep a set of spoken-topic keywords
(content phrases people actually say, not the ministry-portfolio `match` list). We
count, per MK, how many transcript segments mention a topic, and link MK→topic when
that count clears a threshold. Each topic carries its latest official value + source.

Writes docs/data/connections.json. Free (local, no LLM).
"""

from __future__ import annotations

import glob
import json
import os
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))
MIN_SEGMENTS = 2  # an MK must mention a topic in >=2 segments to count as engaged with it

# series key -> (display label, [spoken-topic keywords]). Multi-word phrases keep precision high.
TOPIC_KEYWORDS: dict[str, tuple[str, list[str]]] = {
    "unemployment":   ("אבטלה", ["אבטלה", "מובטלים", "שיעור האבטלה", "דורשי עבודה"]),
    "inflation":      ("יוקר המחיה ואינפלציה", ["אינפלציה", "יוקר המחיה", "יוקר מחיה", "מדד המחירים לצרכן", "עליית המחירים", "ההתייקרויות"]),
    "housing":        ("דיור", ["מחירי הדיור", "מחיר דירה", "מחירי הדירות", "משבר הדיור", "שכר דירה", "משכנתא"]),
    "poverty_rate":   ("עוני", ["תחולת העוני", "קו העוני", "מתחת לקו העוני", "שיעור העוני", "חיים בעוני", "חוסר ביטחון תזונתי"]),
    # tightened: bare "רצח"/"נרצח" over-match political/terror contexts unrelated to the crime-rate stat.
    "crime":          ("פשיעה ורצח", ["פשיעה", "הנרצחים", "מספר הנרצחים", "פשיעה בחברה הערבית", "אלימות בחברה הערבית", "הפשיעה במגזר", "שיעור הרצח", "פשיעה חקלאית"]),
    "transport":      ("תאונות דרכים", ["תאונות דרכים", "הרוגים בתאונות", "בטיחות בדרכים", "תאונת דרכים", "הרוגים בכבישים"]),
    "health":         ("בריאות", ["מערכת הבריאות", "בתי החולים", "מיטות אשפוז", "עומס בבתי החולים", "קופות החולים", "תורים לניתוח"]),
    "education":      ("חינוך ובגרות", ["תעודת בגרות", "זכאות לבגרות", "מערכת החינוך", "שיעור הבגרות", "אחוז הזכאים לבגרות"]),
    "aliyah":         ("עלייה", ["עולים חדשים", "קליטת עלייה", "גל העלייה", "קליטת העלייה"]),
    "gdp_growth":     ("צמיחה ותוצר", ["צמיחת המשק", "הצמיחה במשק", "שיעור הצמיחה", "צמיחת התוצר", "התוצר צמח"]),
    "poverty_food":   ("",  []),  # placeholder removed below if empty
    "debt_to_gdp":    ("חוב ציבורי", ["החוב הציבורי", "יחס החוב לתוצר", "החוב הלאומי", "נטל החוב"]),
    "defense_budget_gdp": ("תקציב ביטחון", ["תקציב הביטחון", "הוצאות הביטחון", "תקציב ביטחוני"]),
    "food_price_index": ("מחירי מזון", ["מחירי המזון", "יוקר המזון", "התייקרות המזון", "מחירי מוצרי המזון"]),
    "life_expectancy": ("תוחלת חיים", ["תוחלת החיים", "תוחלת חיים"]),
    "rd_expenditure_gdp": ("מחקר ופיתוח", ["מחקר ופיתוח", "השקעה במו\"פ", "תקציב המו\"פ", "מו\"פ אזרחי"]),
    "gov_deficit_gdp": ("גירעון תקציבי", ["הגירעון", "גירעון תקציבי", "הגירעון הממשלתי", "גירעון בתקציב"]),
    "mobile_price_index": ("מחירי תקשורת", ["מחירי הסלולר", "מחירי התקשורת", "חבילות הסלולר", "שוק הסלולר"]),
    "renewable_electricity_share": ("אנרגיה מתחדשת", ["אנרגיה מתחדשת", "אנרגיות מתחדשות", "אנרגיה סולארית", "אנרגיה ירוקה"]),
    "court_pending_cases": ("בתי משפט", ["התיקים התלויים", "עומס בבתי המשפט", "תיקים תלויים ועומדים", "העומס במערכת המשפט"]),
}
TOPIC_KEYWORDS = {k: v for k, v in TOPIC_KEYWORDS.items() if v[1]}  # drop placeholders


def _roster() -> dict[int, dict]:
    r = json.loads((REPO / "docs" / "data" / "mk_roster.json").read_text(encoding="utf-8"))
    return {int(x["person_id"]): x for x in r}


def _series() -> dict:
    return json.loads((REPO / "docs" / "data" / "portfolio_series.json").read_text(encoding="utf-8")).get("series", {})


def main() -> int:
    roster = _roster()
    series = _series()

    # pid -> topic_key -> segment count
    counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    names: dict[int, str] = {}

    for f in glob.glob(str(DATA / "transcripts" / "person-*" / "*.json")):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        try:
            pid = int(d.get("person_id"))
        except (TypeError, ValueError):
            continue
        names[pid] = d.get("mk_name")
        for s in d.get("segments", []):
            t = s.get("text") or ""
            if not t:
                continue
            for key, (_, kws) in TOPIC_KEYWORDS.items():
                if any(kw in t for kw in kws):
                    counts[pid][key] += 1

    topics_out = []
    edges = 0
    for key, (label, _) in TOPIC_KEYWORDS.items():
        s = series.get(key, {})
        pts = s.get("points", [])
        latest = pts[-1] if pts else {}
        src = (s.get("sources") or [{}])[0]
        mks = []
        for pid, tc in counts.items():
            w = tc.get(key, 0)
            if w >= MIN_SEGMENTS:
                info = roster.get(pid, {})
                mks.append({
                    "person_id": pid,
                    "name": info.get("name") or names.get(pid) or str(pid),
                    "party": info.get("party") or "",
                    "weight": w,
                })
        mks.sort(key=lambda x: x["weight"], reverse=True)
        edges += len(mks)
        topics_out.append({
            "key": key, "label": label or s.get("label", key), "unit": s.get("unit", ""),
            "official_label": s.get("label", ""),
            "latest": {"year": latest.get("year"), "value": latest.get("value")},
            "source": {"org": src.get("org", ""), "url": src.get("url", "")},
            "keyword": TOPIC_KEYWORDS[key][1][0],  # primary keyword for search deep-link
            "mk_count": len(mks),
            "mks": mks,
        })

    topics_out.sort(key=lambda x: x["mk_count"], reverse=True)
    connected = len({pid for t in topics_out for m in t["mks"] for pid in [m["person_id"]]})
    out = {
        "schema": 1,
        "note": "מתאם בלבד: מי מדבר על מה. אין כאן טענה סיבתית.",
        "totals": {"topics": len(topics_out), "mks_connected": connected, "edges": edges},
        "topics": topics_out,
    }
    dst = REPO / "docs" / "data" / "connections.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"connections: {len(topics_out)} topics, {connected} MKs connected, {edges} edges -> {dst}")
    for t in topics_out[:8]:
        print(f"  {t['label']}: {t['mk_count']} MKs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
