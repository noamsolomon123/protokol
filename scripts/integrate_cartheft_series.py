"""Add the adversarially-verified Israel vehicle-theft yearly series (2017–2025)
to the verified-statistics catalog. Source of record: Knesset MMM doc 4175820
(citing Israel Police FOI 674/23) for 2017–2023; Police Statistical Yearbook 2024
for 2024; Calcalist citing police data for the partial-2025 figure.

This series is the evidence behind the flagship 'missing-context' finding on Ben
Gvir's -20% car-theft claim. Figures copied verbatim from the verification run
(workflow wf_c89831df-7e8); nothing invented. Idempotent on (metric, dim, period).
"""
from __future__ import annotations

import json
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "src/knesset_osint/ingestion/catalogs/verified_statistics.json"
U_MMM = "https://fs.knesset.gov.il/25/Committees/25_cs_mmm_4175820.pdf"
U_YB24 = "https://www.gov.il/BlobFolder/reports/police_statistical_2024/he/%D7%A9%D7%A0%D7%AA%D7%95%D7%9F%20%D7%A1%D7%98%D7%98%D7%99%D7%A1%D7%98%D7%99%202024%20%D7%9E%D7%A9%D7%98%D7%A8%D7%AA%20%D7%99%D7%A9%D7%A8%D7%90%D7%9C%20%D7%9E%D7%95%D7%A0%D7%92%D7%A9.pdf"
U_CAL = "https://www.calcalist.co.il/local_news/car/article/bkhzxv8x11g"

MMM_ORG = "מרכז המחקר והמידע של הכנסת — מצטט תשובת משטרת ישראל לבקשת חופש מידע 674/23 (28.2.2024)"
MMM_Q = "תרשים 1: דיווחים למשטרה על גניבות כלי רכב 2017–2023 — 12,176 / 10,441 / 9,981 / 8,742 / 12,256 / 16,305 / 19,094"

# value, period, source_org, source_url, confirm_quote, note
ROWS = [
    (12176, "2017", MMM_ORG, U_MMM, MMM_Q, ""),
    (10441, "2018", MMM_ORG, U_MMM, MMM_Q, ""),
    (9981, "2019", MMM_ORG, U_MMM, MMM_Q, ""),
    (8742, "2020", MMM_ORG, U_MMM, MMM_Q, "שפל הקורונה (סגרים) — לפני כהונת בן גביר."),
    (12256, "2021", MMM_ORG, U_MMM, MMM_Q,
     "כלכליסט הדפיס בטעות 8,748 ל-2021 (שכפול שפל 2020); הערך הרשמי הוא 12,256."),
    (16305, "2022", MMM_ORG, U_MMM, MMM_Q,
     "השנה המלאה האחרונה לפני כהונת בן גביר (נכנס לתפקיד 29.12.2022). הזינוק 2020→2022 (יותר מפי שניים) ארע תחת הממשלה הקודמת."),
    (19094, "2023", MMM_ORG, U_MMM,
     "בין שנת 2020 לשנת 2023 גדל מספר גניבות כלי הרכב בישראל יותר מפי שניים — 16,305 (2022) → 19,094 (2023)",
     "שיא כל-הזמנים; שנתו המלאה הראשונה של בן גביר. דיווחי תקשורת מאוחרים העלו את 2023 עד ~19,982."),
    (18638, "2024", "משטרת ישראל — השנתון הסטטיסטי 2024, לוח 1.9 (פרסום רשמי gov.il)", U_YB24,
     "בשנת 2024 היו 18,638 גניבות כלי רכב מתוך 4,220,410 כלי רכב מנועיים.",
     "צי הרכב גדל ~25% מאז 2017 — המקור הרשמי ממליץ להשוות שיעור-לכלי-רכב ולא מספר מוחלט לאורך זמן."),
    (15153, "2025", "כלכליסט — מצטט נתוני משטרת ישראל (נתון חלקי נכון ל-22.12.2025, לא שנה מלאה)", U_CAL,
     "כך, נכון להיום, ימים אחדים לפני סוף השנה האזרחית, נרשמו בישראל 15,153 גניבות רכב.",
     "ירידה של ~19% לעומת 2024 ('הנמוך ביותר מאז 2021'); ירידה זו מיוחסת בין היתר לחיזוקי-אבטחה של יצרניות רכב סיניות מסוף 2024, לא רק למדיניות. עדיין גבוה ~39% מממוצע 2018–2021 ו-~7% מתחת ל-2022."),
]


def main() -> None:
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    existing = {(p["metric"], p["dimension_value"], p["period"]) for p in cat["data_points"]}
    added = 0
    for value, period, org, url, quote, note in ROWS:
        key = ("vehicle_theft_count", "ארצי", period)
        if key in existing:
            continue
        cat["data_points"].append({
            "metric": "vehicle_theft_count", "dimension_type": "national", "dimension_value": "ארצי",
            "value": value, "unit": "count", "period": period,
            "source_org": org, "source_url": url, "verified": True,
            "confirm_quote": quote, "notes": note,
        })
        existing.add(key)
        added += 1
    cat["count"] = len(cat["data_points"])
    cat["curated"] = "2026-06-28"
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"added={added} total_points={cat['count']} "
          f"distinct_metrics={len({p['metric'] for p in cat['data_points']})}")


if __name__ == "__main__":
    main()
