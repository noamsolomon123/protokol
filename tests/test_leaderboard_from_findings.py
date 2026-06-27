"""Tests for verification.leaderboard.build_leaderboard_rows — the findings->board
wiring, including the integrity rule that only human-confirmed contradictions count.
"""

from __future__ import annotations

from knesset_osint.verification.leaderboard import build_leaderboard_rows

ROSTER = [
    {"person_id": 1, "name": "ח״כ אלף", "party": "סיעה א"},
    {"person_id": 2, "name": "ח״כ בית", "party": "סיעה ב"},
]


def _f(pid, outcome="contradicted", status="confirmed"):
    return {"person_id": pid, "mk_name": f"id{pid}", "outcome": outcome, "status": status}


def test_only_confirmed_contradictions_count():
    findings = [
        _f(1, status="confirmed"),
        _f(1, status="confirmed"),
        _f(1, status="candidate"),      # excluded: not human-reviewed
        _f(2, outcome="consistent", status="confirmed"),  # excluded: not a contradiction
    ]
    rows = build_leaderboard_rows(findings, ROSTER)
    assert rows == [
        {"slug": "person-1", "full_name": "ח״כ אלף", "party": "סיעה א", "contradicted_count": 2}
    ]


def test_all_candidates_yield_empty_board():
    # The live state today: every finding is a candidate -> board is honestly empty.
    findings = [_f(1, status="candidate"), _f(2, status="candidate")]
    assert build_leaderboard_rows(findings, ROSTER) == []


def test_sorted_desc_and_party_from_roster():
    findings = [_f(1), _f(2), _f(2), _f(2)]
    rows = build_leaderboard_rows(findings, ROSTER)
    assert [r["slug"] for r in rows] == ["person-2", "person-1"]  # 3 before 1
    assert rows[0]["party"] == "סיעה ב"
