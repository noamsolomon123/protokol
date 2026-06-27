"""Build docs/data/minister_trends.json — a per-minister portfolio-trend signal for
the green/red arrow on the directory cards.

For each minister we match their ministry/position to a portfolio series (same logic
as ministers.html), then compare the official metric at the year they took office to
the latest year. The arrow is coloured by whether that DIRECTION is favourable for
that metric (GDP up = good; road deaths up = bad). It is the DATA TREND during tenure
— NOT a causal verdict on the person (kept consistent with the data-only rule).
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Does the metric going UP count as favourable? True/False, or None = ambiguous (no arrow).
GOOD_UP = {
    "transport": False, "housing": False, "health": True, "crime": False,
    "education": True, "inflation": False, "aliyah": True, "unemployment": False,
    "gdp_growth": True, "poverty_rate": False, "debt_to_gdp": False,
    "defense_budget_gdp": None, "food_price_index": False, "life_expectancy": True,
    "rd_expenditure_gdp": True, "gov_deficit_gdp": False,
    "renewable_electricity_share": True, "court_pending_cases": False,
    "mobile_price_index": None,  # %-change series — direction ambiguous, no arrow
}


def _match(m: dict, series: dict):
    for key, s in series.items():
        kws = s.get("match", []) or []
        if any(k in (m.get("position", "") or "") or k in (m.get("ministry", "") or "") for k in kws):
            return key, s
    return None, None


def _norm(name: str) -> str:
    return (name or "").strip().replace('"', "").replace("'", "").replace("׳", "").replace("״", "")


def main() -> int:
    ministers = json.loads((REPO / "docs" / "data" / "ministers.json").read_text(encoding="utf-8")).get("ministers", [])
    series = json.loads((REPO / "docs" / "data" / "portfolio_series.json").read_text(encoding="utf-8")).get("series", {})
    # Resolve each minister to the roster's person_id (ministers.json sometimes uses a
    # different id), matched by name, so the badge attaches to the directory card.
    roster = json.loads((REPO / "docs" / "data" / "mk_roster.json").read_text(encoding="utf-8"))
    name2pid = {_norm(r.get("name", "")): str(r.get("person_id")) for r in roster}

    trends: dict[str, dict] = {}
    for m in ministers:
        pid = name2pid.get(_norm(m.get("name", "")), str(m.get("person_id")))
        if trends.get(pid, {}).get("direction") in ("good", "bad"):
            continue  # already have a decisive arrow for this person
        key, s = _match(m, series)
        if not s:
            continue
        pts = s.get("points", [])
        if len(pts) < 2:
            continue
        tyn = int(str(m.get("start_date", ""))[:4] or 0) or None
        start = None
        if tyn:
            start = next((p for p in pts if p["year"] == tyn), None) or next((p for p in pts if p["year"] >= tyn), None)
        start = start or pts[0]
        last = pts[-1]
        if start["year"] == last["year"]:
            continue
        delta = last["value"] - start["value"]
        gd = GOOD_UP.get(key)
        if gd is None or delta == 0:
            direction = "neutral"
        else:
            direction = "good" if ((delta > 0) == gd) else "bad"
        if pid in trends and direction == "neutral":
            continue
        trends[pid] = {
            "direction": direction, "label": s.get("label", ""), "unit": s.get("unit", ""),
            "from_year": start["year"], "from_value": start["value"],
            "to_year": last["year"], "to_value": last["value"],
            "ministry": m.get("ministry", ""), "key": key,
        }

    decisive = sum(1 for t in trends.values() if t["direction"] in ("good", "bad"))
    (REPO / "docs" / "data" / "minister_trends.json").write_text(
        json.dumps({"schema": 1, "trends": trends}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"minister_trends.json: {len(trends)} ministers matched, {decisive} with a green/red arrow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
