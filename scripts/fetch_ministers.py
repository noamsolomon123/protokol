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
    positions = odata_all("KNS_Position", {"$select": "Id,Description"})
    min_pos = {p["Id"]: (p.get("Description") or "") for p in positions if is_minister(p.get("Description") or "")}
    print(f"{len(min_pos)} minister position types; sample: {list(min_pos.values())[:8]}")

    holders = odata_all(
        "KNS_PersonToPosition",
        {"$filter": f"KnessetNum eq {KNESSET} and IsCurrent eq true",
         "$select": "PersonID,PositionID,GovMinistryName,DutyDesc,StartDate,FinishDate"},
    )
    cur = [h for h in holders if h.get("PositionID") in min_pos]
    print(f"{len(cur)} current minister appointments")

    pids = sorted({h["PersonID"] for h in cur})
    persons: dict[int, str] = {}
    for i in range(0, len(pids), 40):
        chunk = pids[i : i + 40]
        flt = "(" + " or ".join(f"Id eq {x}" for x in chunk) + ")"
        for p in odata_all("KNS_Person", {"$filter": flt, "$select": "Id,FirstName,LastName"}):
            persons[p["Id"]] = f"{p.get('FirstName','')} {p.get('LastName','')}".strip()

    ministers = []
    for h in cur:
        ministers.append({
            "person_id": h["PersonID"],
            "name": persons.get(h["PersonID"], ""),
            "position": min_pos.get(h["PositionID"], "").strip(),
            "ministry": (h.get("GovMinistryName") or "").strip(),
            "duty": (h.get("DutyDesc") or "").strip(),
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
