"""Export multi-year series from the verified-statistics catalog to
docs/data/catalog_series.json, so the public 'הנתונים הרשמיים' (statistics) page
can chart them alongside the curated portfolio series.

Only metrics that are genuine TIME SERIES (>=3 distinct yearly periods for a single
dimension) are exported. Metrics that duplicate a curated portfolio series (inflation,
unemployment, general poverty, food/home price index) are skipped to avoid showing the
same thing twice. Figures come straight from the catalog (already adversarially
verified); nothing is computed or invented here.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "src/knesset_osint/ingestion/catalogs/verified_statistics.json"
OUT = REPO / "docs/data/catalog_series.json"

# metric -> (short Hebrew label, category label matching statistics.html groups).
# Only these are surfaced; everything else (duplicates / single-point facts) is omitted.
INCLUDE = {
    "vehicle_theft_count": ("גניבות רכב בישראל", "ביטחון, פשיעה ומשפט"),
    "femicide_victims_count": ("נשים שנרצחו בישראל", "ביטחון, פשיעה ומשפט"),
    "homicide_victims_count": ("נרצחים בישראל (סך הכל)", "ביטחון, פשיעה ומשפט"),
    "arab_society_homicide_count": ("נרצחים בחברה הערבית", "ביטחון, פשיעה ומשפט"),
    "arab_population_share_pct": ("שיעור הערבים מהאוכלוסייה", "חברה, רווחה וחינוך"),
    "haredi_men_employment_rate_pct": ("תעסוקת גברים חרדים", "חברה, רווחה וחינוך"),
    "poverty_rate_arab_pct": ("עוני במשפחות ערביות", "חברה, רווחה וחינוך"),
    "poverty_rate_haredi_pct": ("עוני במשפחות חרדיות", "חברה, רווחה וחינוך"),
    "housing_years_of_income": ("שנות שכר לרכישת דירה", "דיור, תחבורה ואנרגיה"),
    "avg_monthly_wage_per_post_nis": ("שכר חודשי ממוצע למשרה", "כלכלה ויוקר המחיה"),
}
MIN_PERIODS = 3


def _year(period: str) -> int | None:
    """Pull a 4-digit year out of a period string ('2024', 'תשפ\"ו (2025)' …)."""
    digits = ""
    for ch in period:
        if ch.isdigit():
            digits += ch
            if len(digits) == 4:
                return int(digits)
        else:
            digits = ""
    return None


def main() -> None:
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_metric: dict[str, list[dict]] = collections.defaultdict(list)
    for p in cat["data_points"]:
        by_metric[p["metric"]].append(p)

    series: dict[str, dict] = {}
    for metric, (label, category) in INCLUDE.items():
        pts = by_metric.get(metric, [])
        if not pts:
            continue
        # The year may live in `period` OR (for some metrics) in `dimension_value`.
        # Group one value per year (national/ארצי wins a same-year collision).
        year_val: dict[int, float] = {}
        for p in pts:
            y = _year(str(p.get("period", ""))) or _year(str(p.get("dimension_value", "")))
            if y is None:
                continue
            if y not in year_val or p.get("dimension_value") in ("ארצי", "national"):
                year_val[y] = p["value"]
        if len(year_val) < MIN_PERIODS:
            continue
        points = [{"year": y, "value": year_val[y]} for y in sorted(year_val)]
        # distinct sources (org,url), cap 2
        seen, sources = set(), []
        for p in pts:
            key = (p.get("source_org", ""), p.get("source_url", ""))
            if key[1] and key not in seen:
                seen.add(key)
                sources.append({"org": p["source_org"].split(" — ")[0].split(" (")[0][:60], "url": p["source_url"]})
            if len(sources) >= 2:
                break
        unit = pts[0].get("unit", "")
        unit_he = {"count": "מספר מוחלט לשנה", "percent": "אחוז (%)", "%": "אחוז (%)",
                   "years": "שנות שכר", "nis": "ש\"ח"}.get(unit, unit)
        note = (pts[-1].get("notes") or pts[0].get("notes") or "")[:240]
        series[metric] = {
            "label": label, "unit": unit_he, "category": category,
            "points": points, "sources": sources, "note": note,
        }

    OUT.write_text(json.dumps({"schema": 1, "source": "verified_statistics catalog",
                               "count": len(series), "series": series},
                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"catalog_series.json: {len(series)} series — {', '.join(series)}")


if __name__ == "__main__":
    main()
