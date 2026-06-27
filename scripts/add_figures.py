"""Add prominent political figures who are NOT sitting MKs — former PMs, party
leaders, and ministers who resigned their Knesset seat under the Norwegian Law —
to the harvest roster, so the platform also tracks their interviews + tweets and
fact-checks them. Idempotent by name. Re-run after editing FIGURES to add more.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# person_id 99xxxx marks a non-MK tracked figure (distinct from real Knesset ids).
FIGURES = [
    {"person_id": 990001, "name": "נפתלי בנט", "role": "ראש הממשלה ה-13 לשעבר"},
    {"person_id": 990002, "name": "גדי אייזנקוט", "role": "רמטכ\"ל לשעבר, מנהיג מדיני"},
    {"person_id": 990003, "name": "יאיר גולן", "role": "יו\"ר מפלגת 'הדמוקרטים'"},
    {"person_id": 990004, "name": "בצלאל סמוטריץ'", "role": "שר האוצר (התפטר מהכנסת – חוק נורבגי)"},
    {"person_id": 990005, "name": "גדעון סער", "role": "שר החוץ (התפטר מהכנסת – חוק נורבגי)"},
    {"person_id": 990006, "name": "יואב גלנט", "role": "שר הביטחון לשעבר"},
]
PARTY = "דמויות פוליטיות בולטות · אינם ח״כ מכהנים"


def main() -> int:
    p = REPO / "docs" / "data" / "mk_roster.json"
    roster = json.loads(p.read_text(encoding="utf-8"))
    names = [r.get("name", "") for r in roster]
    added = []
    for f in FIGURES:
        if any(f["name"] in n or n == f["name"] for n in names):
            continue  # already present
        roster.append({"person_id": f["person_id"], "name": f["name"], "party": PARTY, "role": f["role"], "is_mk": False})
        added.append(f["name"])
    p.write_text(json.dumps(roster, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"roster now {len(roster)} entries (+{len(added)} figures): {added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
