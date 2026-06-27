"""Integrate verified research series (from a minister-performance research workflow
output) into the site. Each verified series feeds the performance tab
(portfolio_series.json); series that map to a fact-check TOPIC also become
year-dimensioned points in the verified-statistics catalog, expanding what the
fact-check can check. Idempotent (tagged `from_research`).

    python scripts/integrate_research_series.py <workflow_result.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Series whose metric maps to an existing fact-check topic -> catalog metric name
# (chosen so factcheck.TOPIC_KEYWORDS routes it: 'poverty'->עוני, 'price'->יוקר).
TOPIC_CATALOG_METRIC = {
    "poverty_rate": "poverty_rate_pct",
    "food_price_index": "food_price_index",
}


def load_verified(p: str) -> list[dict]:
    raw = json.loads(Path(p).read_text(encoding="utf-8"))
    d = raw.get("result", raw) if isinstance(raw, dict) else raw
    return d.get("verified", [])


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: integrate_research_series.py <workflow_result.json>")
        return 1
    verified = load_verified(sys.argv[1])

    # 1) Performance tab series.
    ps_path = REPO / "docs" / "data" / "portfolio_series.json"
    ps = json.loads(ps_path.read_text(encoding="utf-8"))
    for s in verified:
        ps["series"][s["key"]] = {
            "label": s.get("label", ""),
            "unit": s.get("unit", ""),
            "match": s.get("ministry_match", []),
            "note": (s.get("note", "") or "")[:600],
            "sources": [{"org": s.get("source_org", ""), "url": s.get("source_url", "")}],
            "points": s.get("points", []),
            "from_research": True,
        }
    ps_path.write_text(json.dumps(ps, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2) Catalog points for topic-mapped series only.
    cat_path = REPO / "src" / "knesset_osint" / "ingestion" / "catalogs" / "verified_statistics.json"
    cat = json.loads(cat_path.read_text(encoding="utf-8"))
    # Per-metric idempotency: only drop the from_research points for metrics THIS
    # run re-adds — never wipe unrelated research metrics from earlier runs.
    run_metrics = {TOPIC_CATALOG_METRIC[s["key"]] for s in verified if s.get("key") in TOPIC_CATALOG_METRIC}
    points = [p for p in cat["data_points"]
              if not (p.get("from_research") and p.get("metric") in run_metrics)]
    added = 0
    for s in verified:
        metric = TOPIC_CATALOG_METRIC.get(s["key"])
        if not metric:
            continue
        org, url = s.get("source_org", ""), s.get("source_url", "")
        unit = (s.get("unit", "") or "")[:24]
        for pt in s.get("points", []):
            points.append({
                "metric": metric, "dimension_type": "year", "dimension_value": str(pt["year"]),
                "value": pt["value"], "unit": unit, "period": str(pt["year"]),
                "source_org": org, "source_url": url,
                "confirm_quote": f"{s.get('label','')[:40]}: {pt['year']} = {pt['value']}",
                "from_research": True,
            })
            added += 1
    cat["data_points"] = points
    cat["count"] = len(points)
    cat_path.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"portfolio_series += {len(verified)} series; catalog += {added} topic-mapped points (now {len(points)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
