"""Fact-check core: extract checkable claims from a transcript and adjudicate
each against the verified official statistics — producing CANDIDATE findings.

Findings from transcripts are CANDIDATES for human review (transcription can
mis-hear a quote), never auto-published verdicts. Adjudication uses Gemini but
is constrained to the REAL numbers in the provided verified stats (it compares,
it does not invent figures); every finding carries the stat's source.
"""

from __future__ import annotations

import json
from pathlib import Path

from knesset_osint.ingestion.transcription.keys import GeminiKeyPool
from knesset_osint.verification.gemini_llm import gemini_generate_json

# The 6 topics for which we have adversarially-verified official statistics.
TOPICS = [
    'גיוס לצה"ל ושיעורי גיוס (כללי / חרדים / מגזרים)',
    "יוקר המחיה ואינפלציה (מדד המחירים לצרכן)",
    "אבטלה, תעסוקה ושכר",
    "מחירי דיור ושכר דירה",
    "פשיעה וביטחון אישי",
    "עוני ואי-שוויון",
]

# Map a topic to the metric keywords that belong to it (for selecting stats).
TOPIC_KEYWORDS = {
    "גיוס": ["idf", "enlist", "haredi", "draft", "torato", "exempt", "conscript", "service"],
    "יוקר": ["cpi", "inflation", "price", "cost", "consumer"],
    "אבטל": ["unemploy", "wage", "employ", "labor", "labour", "salary", "job"],
    "תעסוק": ["unemploy", "wage", "employ", "labor", "labour", "salary", "job"],
    "דיור": ["home", "hous", "rent", "dwell", "apartment", "mortgage"],
    "פשיע": ["crime", "homicide", "murder", "assault", "police", "offens", "violence"],
    "ביטחון": ["crime", "homicide", "murder", "assault", "police", "offens", "violence"],
    "עוני": ["poverty", "gini", "inequal", "poor"],
}

_EXTRACT_PROMPT = """לפניך תמלול של דברי פוליטיקאי/ת ישראלי/ת. יש לנו נתונים רשמיים לבדיקה אך ורק על הנושאים הבאים:
{topics}

חלץ כל אמירה עובדתית הניתנת לבדיקה שנאמרה ושקשורה לאחד הנושאים — אמירה עם מספר, אחוז, השוואה, סופרלטיב ("הכי", "הנמוך/הגבוה ביותר") או מגמה ("עלה", "ירד", "הוכפל") שניתן לאשר או להפריך מול נתון רשמי. התעלם מדעות, הבטחות, והצהרות כלליות.
החזר JSON תקין בלבד — מערך של {{"quote": ציטוט מדויק, "topic": הנושא מהרשימה, "claim": תקציר הטענה, "approx_seconds": שנייה משוערת}}. אם אין — החזר [].

התמלול:
{transcript}"""

_ADJ_PROMPT = """אתה בודק עובדות אובייקטיבי. לפניך טענה של פוליטיקאי/ת ולצדה נתונים רשמיים מאומתים (כל אחד עם מקור).
קבע אם הטענה סותרת את הנתונים הרשמיים, תואמת אותם, או שלא ניתן להכריע על בסיס הנתונים שסופקו.
חוק ברזל: השתמש אך ורק במספרים שבנתונים שסופקו. אל תמציא ואל תניח מספרים.

הטענה: "{claim}"
ציטוט: "{quote}"

נתונים רשמיים זמינים (index : נתון):
{stats}

החזר JSON: {{"outcome": "contradicted" | "consistent" | "unverifiable", "stat_index": מספר הנתון הרלוונטי או null, "confidence": מספר בין 0 ל-1, "reason": הסבר קצר בעברית המבוסס על המספרים}}."""


def load_verified_stats(repo_root: Path) -> list[dict]:
    p = repo_root / "src" / "knesset_osint" / "ingestion" / "catalogs" / "verified_statistics.json"
    return json.loads(p.read_text(encoding="utf-8")).get("data_points", [])


def _topic_key(topic_str: str) -> str | None:
    for key in TOPIC_KEYWORDS:
        if key in (topic_str or ""):
            return key
    return None


def stats_for_topic(all_stats: list[dict], topic_str: str) -> list[dict]:
    key = _topic_key(topic_str)
    if not key:
        return []
    kws = TOPIC_KEYWORDS[key]
    return [s for s in all_stats if any(k in (s.get("metric", "") or "").lower() for k in kws)]


def transcript_text(d: dict, max_chars: int = 14000) -> str:
    return " ".join(s.get("text", "") for s in d.get("segments", []))[:max_chars]


def extract_claims(pool: GeminiKeyPool, transcript: dict, *, model: str = "gemini-2.5-flash") -> list[dict]:
    prompt = _EXTRACT_PROMPT.format(
        topics="\n".join("- " + t for t in TOPICS), transcript=transcript_text(transcript)
    )
    claims = gemini_generate_json(pool, prompt, model=model)
    return claims if isinstance(claims, list) else []


def adjudicate(pool: GeminiKeyPool, claim: str, quote: str, stats: list[dict], *, model: str = "gemini-2.5-flash") -> dict:
    stat_lines = "\n".join(
        f'{i}: {s.get("metric")} | {s.get("dimension_value","")} = {s.get("value")} {s.get("unit","")} '
        f'({s.get("period","")}) — מקור: {s.get("source_org","")}'
        for i, s in enumerate(stats)
    )
    prompt = _ADJ_PROMPT.format(claim=claim, quote=quote, stats=stat_lines)
    res = gemini_generate_json(pool, prompt, model=model)
    return res if isinstance(res, dict) else {"outcome": "unverifiable", "stat_index": None, "confidence": 0, "reason": ""}
