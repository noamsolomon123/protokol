"""Add the verified portfolio TIME-SERIES (housing/inflation/unemployment/crime)
into the fact-check stats catalog, so the strict pipeline can check yearly
value/trend claims (e.g. "inflation in 2022 was 5%"). Idempotent.
"""

from __future__ import annotations

import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]

# Only series that map to the 6 fact-check topics (transport/education/aliyah are
# minister-perf only, not fact-check topics). metric names are chosen so the
# existing TOPIC_KEYWORDS in factcheck.py route them to the right topic.
MAP = {
    "housing": "home_price_index",
    "inflation": "cpi_annual_inflation_pct",
    "unemployment": "unemployment_rate_pct",
    "crime": "homicide_victims_count",
}


def main() -> int:
    ps = json.loads((REPO / "docs/data/portfolio_series.json").read_text(encoding="utf-8"))["series"]
    cat_path = REPO / "src/knesset_osint/ingestion/catalogs/verified_statistics.json"
    cat = json.loads(cat_path.read_text(encoding="utf-8"))
    points = [p for p in cat["data_points"] if not p.get("from_portfolio")]  # idempotent

    added = 0
    for key, metric in MAP.items():
        s = ps.get(key)
        if not s:
            continue
        src = (s.get("sources") or [{}])[0]
        for pt in s.get("points", []):
            points.append({
                "metric": metric,
                "dimension_type": "year",
                "dimension_value": str(pt["year"]),
                "value": pt["value"],
                "unit": s.get("unit", ""),
                "period": str(pt["year"]),
                "source_org": src.get("org", ""),
                "source_url": src.get("url", ""),
                "confirm_quote": f"{s.get('label','')}: {pt['year']} = {pt['value']}{' (ארעי)' if pt.get('provisional') else ''}",
                "from_portfolio": True,
            })
            added += 1

    cat["data_points"] = points
    cat["count"] = len(points)
    cat_path.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"catalog now {len(points)} stats (+{added} time-series points)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
