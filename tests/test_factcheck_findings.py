"""Tests for factcheck.build_findings_for_transcript (the shared serial/parallel
fact-check core), driven by a fake LLM so no network/quota is touched.

The fake distinguishes the two prompt types: the adjudication prompt opens with
"אתה בודק עובדות"; everything else is a claim-extraction call.
"""

from __future__ import annotations

from knesset_osint.verification import factcheck as fc

# A stat whose metric matches the "יוקר" (cost-of-living) topic keywords (cpi/inflation).
INFLATION_STAT = {
    "metric": "cpi_annual_inflation_pct", "dimension_type": "year", "dimension_value": "2022",
    "value": 5.3, "unit": "%", "period": "2022", "source_org": 'למ"ס',
    "source_url": "https://example.gov.il", "confirm_quote": "2022 = 5.3%",
}

TRANSCRIPT = {
    "person_id": 42, "mk_name": "ח״כ לדוגמה", "video_id": "vid123",
    "url": "https://youtu.be/vid123", "title": "ראיון",
    "segments": [{"start": 0, "end": 5, "text": "האינפלציה ב-2022 הייתה אפס אחוז"}],
}

CLAIM = [{"quote": "האינפלציה ב-2022 הייתה אפס", "topic": "יוקר המחיה ואינפלציה (מדד המחירים לצרכן)",
          "claim": "אינפלציה 2022 = 0%", "approx_seconds": 3}]


def _gen(adj_outcome: str, *, stat_index=0, calls=None):
    def gen(prompt: str):
        if calls is not None:
            calls.append("adj" if prompt.startswith("אתה בודק עובדות") else "extract")
        if prompt.startswith("אתה בודק עובדות"):
            return {"outcome": adj_outcome, "stat_index": stat_index, "confidence": 0.9, "reason": "בדיקה"}
        return CLAIM
    return gen


def test_contradiction_becomes_a_finding():
    findings = fc.build_findings_for_transcript(_gen("contradicted"), TRANSCRIPT, [INFLATION_STAT])
    assert len(findings) == 1
    f = findings[0]
    assert f["outcome"] == "contradicted"
    assert f["person_id"] == 42 and f["video_id"] == "vid123"
    assert f["stat"]["metric"] == "cpi_annual_inflation_pct"
    assert f["stat"]["source_url"] == "https://example.gov.il"
    assert f["status"] == "candidate"


def test_unverifiable_verdict_produces_no_finding():
    findings = fc.build_findings_for_transcript(_gen("unverifiable"), TRANSCRIPT, [INFLATION_STAT])
    assert findings == []


def test_no_matching_stat_skips_adjudication():
    # Empty stat catalog -> stats_for_topic returns [] -> adjudication never runs.
    calls: list[str] = []
    findings = fc.build_findings_for_transcript(_gen("contradicted", calls=calls), TRANSCRIPT, [])
    assert findings == []
    assert "adj" not in calls  # we never spent an LLM call adjudicating without a stat
