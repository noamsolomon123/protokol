"""Integrate the adversarially-verified catalog-expansion results (workflow wf_1a36f381)
into the verified-statistics catalog.

PM-review discipline applied here:
  * Only metrics the verifier confirmed by personally reading the official PDF are added.
  * Figures are copied VERBATIM from the verifier's confirmation; no value is invented.
  * The Haredi-poverty metric came back verified=false ONLY because its 2021 figure was
    mis-attributed to the wrong report; its 2022 & 2023 values WERE personally confirmed
    in the cited PDF, so we integrate those two and DROP 2021.
  * housing_years_of_income stores annual figures = the source's raw MONTHLY salary
    counts / 12 (an arithmetic, disclosed transform); the raw monthly figure is kept in
    each note so provenance stays exact.

Idempotent: a (metric, dimension_value, period) already present is skipped. Run again
safely. Writes back with ensure_ascii=False, indent=2, and bumps `count` + `curated`.
"""
from __future__ import annotations

import json
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "src/knesset_osint/ingestion/catalogs/verified_statistics.json"

MMM = "מרכז המחקר והמידע של הכנסת (ממ\"מ)"

# --- source URLs (official, reachable, personally read by the verifier) ---
U_FEMICIDE = "https://fs.knesset.gov.il/globaldocs/MMM/1a9317eb-97c4-f011-a865-005056aa9911/2_1a9317eb-97c4-f011-a865-005056aa9911_11_21126.pdf"
U_ENLIST = "https://fs.knesset.gov.il/globaldocs/MMM/32b8ae93-49cc-ef11-a856-005056aa1f91/2_32b8ae93-49cc-ef11-a856-005056aa1f91_11_20777.pdf"
U_ARABHOM = "https://fs.knesset.gov.il/globaldocs/MMM/f13d1671-a6e1-f011-a866-005056aa9911/2_f13d1671-a6e1-f011-a866-005056aa9911_11_21359.pdf"
U_ONI2023 = "https://www.btl.gov.il/Publications/oni_report/Documents/dohaoni2023.pdf"
U_ONI2024 = "https://www.btl.gov.il/Publications/oni_report/Documents/dohahoni2024.pdf"
U_PRICE = "https://fs.knesset.gov.il/globaldocs/MMM/fe8a69b9-fe38-ef11-8162-005056aa4246/2_fe8a69b9-fe38-ef11-8162-005056aa4246_11_20610.pdf"
U_HOUSING = "https://fs.knesset.gov.il/globaldocs/MMM/e2bce121-c1e3-eb11-8127-00155d0af32a/2_e2bce121-c1e3-eb11-8127-00155d0af32a_11_18086.pdf"
U_TEACHER = "https://fs.knesset.gov.il/globaldocs/MMM/6e2f65ad-4a40-f011-a85f-005056aa9911/2_6e2f65ad-4a40-f011-a85f-005056aa9911_11_21429.pdf"


def dp(metric, dtype, dval, value, unit, period, org, url, quote, notes):
    return {
        "metric": metric, "dimension_type": dtype, "dimension_value": dval,
        "value": value, "unit": unit, "period": period,
        "source_org": org, "source_url": url, "verified": True,
        "confirm_quote": quote, "notes": notes,
    }


NEW: list[dict] = []

# 1) Femicide victims (police, via MMM doc 21126) — 2015..2024, all from one consistent series.
_fem = {2015: 28, 2016: 28, 2017: 21, 2018: 29, 2019: 17, 2020: 29, 2021: 27, 2022: 23, 2023: 32, 2024: 35}
_fem_quote = ("תרשים 1 ותרשים 3, 'סך הכל נרצחות': "
              "2015=28, 2016=28, 2017=21, 2018=29, 2019=17, 2020=29, 2021=27, 2022=23, 2023=32, 2024=35")
for yr, v in _fem.items():
    NEW.append(dp(
        "femicide_victims_count", "national", "כלל הנשים שנרצחו בישראל", v, "count", str(yr),
        "מרכז המחקר והמידע של הכנסת (מקור: מדור נפגעי עבירה, אגף החקירות והמודיעין, משטרת ישראל)",
        U_FEMICIDE, _fem_quote,
        "מסמך 'נתונים על רצח נשים, 2015–2025' (24.11.2025). רצח פלילי, כל הגילים, לא רק על רקע מגדרי; "
        "אינו כולל פח\"ע. סך העשור 269 נרצחות, ממוצע ~27/שנה, שיא 2024=35. ~30% מהתיקים טרם פוענחו "
        "(46% ברצח נשים ערביות). 2025 חלקית (35 עד 7.9) — הושמטה כשנה מלאה.",
    ))

# 2) IDF enlistment rate by sector (MMM doc 20777, 2020 graduating cohort) — 4 sectors.
_enl = [
    ("חילוני (יהודי ממלכתי)", 88.5),
    ("ציוני-דתי (יהודי ממלכתי-דתי)", 84.3),
    ("דרוזי", 69.2),
    ("חרדי (יהודי)", 13.5),
]
_enl_quote = ("בוגרי מערכת החינוך שסיימו לימודיהם בשנת תש\"ף (2020): יהודי ממלכתי 88.5%, "
              "יהודי ממלכתי-דתי 84.3%, דרוזי 69.2%, יהודי חרדי 13.5%")
for dval, v in _enl:
    NEW.append(dp(
        "idf_enlistment_rate_by_sector", "sector", dval, v, "percent", "2020",
        MMM, U_ENLIST, _enl_quote,
        "מתוך מי שצה\"ל הגדיר כ'מחויבי גיוס' (לא מכלל שכבת הגיל), בוגרי מוסדות בפיקוח משרד החינוך, "
        "נתוני 'התמונה החינוכית' תשפ\"ג. למגזר הערבי/בדואי 'אין מידע' על גיוס צבאי — רק התנדבות "
        "לשירות לאומי-אזרחי (ערבי 3.6%, בדואי 9.3%). הגדרת 'חרדי' לפי מודל למ\"ס; ~70% מבוגרי החינוך "
        "החרדי שמתגייסים אינם מגדירים עצמם חרדים — להיזהר בהשוואות. מסמך 6.1.2025.",
    ))

# 3) Arab-society homicide victims (MMM doc 21359; police FOI) — 2023, 2024.
_arab = {2023: 236, 2024: 224}
for yr, v in _arab.items():
    NEW.append(dp(
        "arab_society_homicide_count", "sector", "החברה הערבית", v, "count", str(yr),
        "מרכז המחקר והמידע של הכנסת (מקור: משטרת ישראל, תשובה לבקשת חופש מידע)",
        U_ARABHOM, "חלה ירידה במספר הנרצחים הערבים הכולל מ-236 ב-2023 ל-224 ב-2024",
        "קורבנות רצח פלילי (בני אדם, כל הגילים ושני המגדרים; 37 נשים מתוך 460 ב-2023–2024). "
        "אינו כולל הרוגי טרור (7.10). שונה מ'אירועי רצח' (210 ב-2023, 206 ב-2024) ומ'נשים שנרצחו'. "
        "הערבים ~79% מכלל הנרצחים בישראל. נתוני 2025 טרם פורסמו רשמית. מסמך 29.12.2025.",
    ))

# 4) Arab-family poverty incidence (NII annual report) — 2022,2023 from dohaoni2023; 2024 from dohahoni2024.
NEW.append(dp(
    "poverty_rate_arab_pct", "sector", "משפחות ערביות", 38.9, "percent", "2022",
    "המוסד לביטוח לאומי, מינהל המחקר והתכנון — דוח ממדי העוני", U_ONI2023,
    "לעומת 2022: המשפחות הערביות מ-38.9% ל-38.4%",
    "תחולת עוני ברמת משפחות לפי הכנסה פנויה (אחרי העברות ומסים), קו עוני=50% מהחציון. ערך כפי "
    "שפורסם בדוח 2023. הערה: דוח 2024 תיקן את 2023 ל-38.1% — לכן יש תפר בסדרה.",
))
NEW.append(dp(
    "poverty_rate_arab_pct", "sector", "משפחות ערביות", 38.4, "percent", "2023",
    "המוסד לביטוח לאומי, מינהל המחקר והתכנון — דוח ממדי העוני", U_ONI2023,
    "לעומת 2022: המשפחות הערביות מ-38.9% ל-38.4%",
    "ערך כפי שפורסם בדוח 2023; דוח 2024 עדכן ל-38.1% (עדכוני משקלי סקר). להשוואת מגמה אחרונה "
    "השתמשו בזוג מאותו דוח (2024): 2023=38.1%, 2024=37.6%.",
))
NEW.append(dp(
    "poverty_rate_arab_pct", "sector", "משפחות ערביות", 37.6, "percent", "2024",
    "המוסד לביטוח לאומי, מינהל המחקר והתכנון — דוח ממדי העוני", U_ONI2024,
    "תחולת העוני ירדה בקרב המשפחות הערביות והחרדיות מ-38.1% ל-37.6%",
    "ערך 2024 מדוח 2024. נותר גבוה פי ~2.5 מיהודים לא-חרדים (~14%).",
))

# 5) Haredi-family poverty incidence — only the personally-confirmed 2022 & 2023 (2021 dropped: mis-attributed).
NEW.append(dp(
    "poverty_rate_haredi_pct", "sector", "משפחות חרדיות", 33.9, "percent", "2022",
    "המוסד לביטוח לאומי, מינהל המחקר והתכנון — דוח ממדי העוני", U_ONI2023,
    "לעומת 2022: ...והחרדיות מ-33.9% ל-33.0%",
    "תחולת עוני ברמת משפחות, הכנסה פנויה. אומת ישירות בדוח 2023. הנתון לנפשות גבוה יותר (~38.5%). "
    "ערך 2021 (34.4%) הושמט — אינו מופיע בדוח 2023 (שייך לדוח 2022).",
))
NEW.append(dp(
    "poverty_rate_haredi_pct", "sector", "משפחות חרדיות", 33.0, "percent", "2023",
    "המוסד לביטוח לאומי, מינהל המחקר והתכנון — דוח ממדי העוני", U_ONI2023,
    "לעומת 2022: ...והחרדיות מ-33.9% ל-33.0%",
    "אומת ישירות בדוח 2023. דוח 2024 נתן 2023=33.0% ו-2024=32.8%.",
))

# 6) Consumer price level vs OECD average (MMM doc 20610, citing OECD) — Dec 2023.
NEW.append(dp(
    "price_level_vs_oecd_pct", "national", "כלל המשק (צריכה פרטית)", 29, "percent", "2023",
    "מרכז המחקר והמידע של הכנסת (מבוסס OECD, Monthly Comparative Price Levels)", U_PRICE,
    "רמת מחירים יחסית של צריכה בדצמבר 2023 היתה גבוהה ב-29% בהשוואה לממוצע ה-OECD",
    "מדד רמת מחירים (לא אינפלציה): ישראל ~29% מעל ממוצע OECD (מדד ≈129). אומדנים חלופיים באותו "
    "מקור: ICP בנק עולמי 2021 ~47% מעל (מקום 3 ב-OECD); PPP-לתוצר 135 ב-2023 מול 102 ב-2012. "
    "מתודולוגיות שונות — לא לאחד לסדרה. מסמך 14.7.2024.",
))

# 7) Housing affordability — gross monthly salaries to buy an avg apartment / 12 (annual). MMM doc 18086.
_house_monthly = {2013: 132.3, 2014: 138.2, 2015: 143.2, 2016: 143.6, 2017: 145.1, 2018: 150.4, 2019: 151.5, 2020: 138.6}
for yr, monthly in _house_monthly.items():
    annual = round(monthly / 12, 1)
    NEW.append(dp(
        "housing_years_of_income", "national", "ארצי", annual, "years", str(yr),
        "מרכז המחקר והמידע של הכנסת (ממ\"מ); מבוסס נתוני הלמ\"ס", U_HOUSING,
        "תרשים 8: יחס מחיר דירה ממוצעת לשכר חודשי ברוטו ממוצע למשרת שכיר; "
        "מ-132.3 משכורות ב-2013 ל-138.6 ב-2020",
        f"ערך גולמי במקור: {monthly} משכורות חודשיות (÷12 = {annual} שנות שכר ברוטו למשרת שכיר בודדת). "
        "גבוה ממדד 'נשיגות הרכישה' של בנק ישראל (הכנסת משק בית נטו, ~5–6.4 שנים). 2020 מוטה כלפי "
        "מטה בשל זינוק השכר בקורונה. מסמך 19.7.2021.",
    ))

# 8) Unfilled teaching positions at school-year opening (MMM doc 21429) — Sept 2025 (תשפ"ו).
NEW.append(dp(
    "teacher_shortage_count", "national", "חינוך רשמי (ארצי)", 498, "count", "2025",
    "מרכז המחקר והמידע של הכנסת (על בסיס נתוני משרד החינוך)", U_TEACHER,
    "בפתיחת שנת הלימודים תשפ\"ו (2025/26)... היו 498 משרות הוראה לא מאוישות, שמהן 222 היו במקצועות הליבה",
    "מספר שיורי אחרי איוש (בתחילת הקיץ חסרו ~5,000, רובם אוישו). מודד משרות פנויות בפועל לפי דיווחי "
    "מנהלים — לא 'מחסור איכותי' ולא פער היצע-ביקוש (מודל ה-AI של משרד החינוך: ~1,800 משרות מלאות "
    "בתשפ\"ה). מסמך 5.2.2026.",
))


def main() -> None:
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    existing = {(p["metric"], p["dimension_value"], p["period"]) for p in cat["data_points"]}
    added, skipped = 0, 0
    for row in NEW:
        key = (row["metric"], row["dimension_value"], row["period"])
        if key in existing:
            skipped += 1
            continue
        cat["data_points"].append(row)
        existing.add(key)
        added += 1
    cat["count"] = len(cat["data_points"])
    cat["curated"] = "2026-06-28"
    note = "phase3 adversarially-verified + 2026-06-28 catalog-expansion (8 metrics, official MMM/NII/Police PDFs)"
    if "expansion" not in cat["source"]:
        cat["source"] = note
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metrics = sorted({p["metric"] for p in cat["data_points"]})
    print(f"added={added} skipped={skipped} total_points={cat['count']} distinct_metrics={len(metrics)}")
    new_metrics = sorted({r["metric"] for r in NEW})
    print("expansion metrics:", ", ".join(new_metrics))


if __name__ == "__main__":
    main()
