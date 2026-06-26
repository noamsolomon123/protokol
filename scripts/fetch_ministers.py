"""Fetch current government ministers + portfolios + tenure from the official
Knesset ParliamentInfo OData (real data, no Gemini). Writes docs/data/ministers.json.

Foundation for the per-minister "performance" tab. (Outcome time-series per
portfolio are added separately; here we get who/what/since-when.)
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from knesset_osint.core.console import enable_utf8_console

REPO = Path(__file__).resolve().parents[1]
BASE = "https://knesset.gov.il/OdataV4/ParliamentInfo"
KNESSET = 25


def odata_all(entity: str, params: dict, cap: int = 12000) -> list[dict]:
    out: list[dict] = []
    p = dict(params)
    p["$format"] = "json"
    url = f"{BASE}/{entity}"
    first = True
    while url and len(out) < cap:
        r = httpx.get(url, params=(p if first else None), timeout=60)
        r.raise_for_status()
        j = r.json()
        out.extend(j.get("value", []))
        url = j.get("@odata.nextLink")
        first = False
    return out


def is_minister(desc: str) -> bool:
    n = (desc or "").strip()
    return (
        n.startswith("שר ") or n.startswith("שרת ") or n.startswith("ראש הממשלה")
        or n.startswith("סגן שר") or n.startswith("סגנית שר") or n.startswith("השר ")
        or n.startswith("ממלא מקום ראש הממשלה")
    )


def main() -> int:
    enable_utf8_console()
    # Current government office-holders: IsCurrent + a ministry attached. The
    # specific portfolio is in DutyDesc (e.g. "שרת התחבורה והבטיחות בדרכים").
    holders = odata_all(
        "KNS_PersonToPosition",
        {"$filter": "IsCurrent eq true and GovMinistryName ne null",
         "$select": "PersonID,PositionID,GovMinistryName,DutyDesc,StartDate,FinishDate"},
    )
    cur = [h for h in holders if is_minister(h.get("DutyDesc") or "")]
    print(f"{len(cur)} current minister/deputy appointments")

    pids = sorted({h["PersonID"] for h in cur})
    # Names: reuse the MK roster (most ministers are sitting MKs); fetch any
    # missing person one-by-one (single-entity fetch avoids the long-OR 400).
    roster = json.loads((REPO / "docs" / "data" / "mk_roster.json").read_text(encoding="utf-8"))
    persons: dict[int, str] = {r["person_id"]: r["name"] for r in roster}
    for pid in pids:
        if pid in persons:
            continue
        try:
            r = httpx.get(f"{BASE}/KNS_Person({pid})", params={"$format": "json"}, timeout=30)
            if r.status_code == 200:
                j = r.json()
                persons[pid] = f"{j.get('FirstName','')} {j.get('LastName','')}".strip()
        except httpx.HTTPError:
            pass

    ministers = []
    for h in cur:
        ministers.append({
            "person_id": h["PersonID"],
            "name": persons.get(h["PersonID"], ""),
            "position": (h.get("DutyDesc") or "").strip(),
            "ministry": (h.get("GovMinistryName") or "").strip(),
            "start_date": h.get("StartDate"),
            "source": f"{BASE}/KNS_PersonToPosition",
        })
    ministers.sort(key=lambda m: m["position"])
    out = REPO / "docs" / "data" / "ministers.json"
    out.write_text(json.dumps({"schema": 1, "knesset": KNESSET, "count": len(ministers), "ministers": ministers},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(ministers)} ministers -> {out}")
    for m in ministers[:30]:
        print(f"  {m['position']} | {m['ministry']} | {m['name']} (since {str(m['start_date'])[:10]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
