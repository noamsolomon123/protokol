"""Integrate verified catalog-research workflow output into the fact-check catalog
(verified_statistics.json) as dimensioned data points. Idempotent via the
`from_catalog_research` tag. Carries only sourced figures (each point keeps its
source_org + source_url); nothing is fabricated.

    python scripts/integrate_catalog_research.py <workflow_result.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_verified(p: str) -> list[dict]:
    raw = json.loads(Path(p).read_text(encoding="utf-8"))
    d = raw.get("result", raw) if isinstance(raw, dict) else raw
    return d.get("verified", [])


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: integrate_catalog_research.py <workflow_result.json>")
        return 1
    verified = load_verified(sys.argv[1])
    cat_path = REPO / "src" / "knesset_osint" / "ingestion" / "catalogs" / "verified_statistics.json"
    cat = json.loads(cat_path.read_text(encoding="utf-8"))
    points = [p for p in cat["data_points"] if not p.get("from_catalog_research")]  # idempotent

    added = 0
    for s in verified:
        metric = s.get("metric")
        if not metric or not s.get("points"):
            continue
        unit = (s.get("unit", "") or "")[:30]
        org, url = s.get("source_org", ""), s.get("source_url", "")
        dtype = s.get("dimension_type", "year")
        for pt in s["points"]:
            dv = str(pt.get("dimension_value"))
            points.append({
                "metric": metric, "dimension_type": dtype, "dimension_value": dv,
                "value": pt.get("value"), "unit": unit,
                "period": str(pt.get("period", dv)), "source_org": org, "source_url": url,
                "confirm_quote": f"{s.get('label','')[:50]}: {dv} = {pt.get('value')}",
                "from_catalog_research": True,
            })
            added += 1

    cat["data_points"] = points
    cat["count"] = len(points)
    cat_path.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"catalog += {added} points from {len(verified)} verified metrics (now {len(points)})")
    for s in verified:
        pts = s.get("points", [])
        rng = f"{pts[0].get('dimension_value')}..{pts[-1].get('dimension_value')}" if pts else "-"
        print(f"  {s.get('metric')}: {len(pts)} pts [{rng}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
