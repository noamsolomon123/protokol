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

_EXTRACT_PROMPT = """לפניך תמלול של דברי פוליטיקאי/ת. יש לנו נתונים רשמיים אך ורק על הנושאים הבאים:
{topics}

חלץ אך ורק טענות עובדתיות קשיחות וניתנות להפרכה — כלומר אמירה שמצהירה על כמות מדידה מסוימת: מספר, אחוז, שיעור, דירוג מפורש ("הכי גבוה/נמוך בארץ", "מקום ראשון"), או מגמה כמותית ברורה ("עלה ב-X%", "ירד", "הוכפל"). הטענה חייבת להיות כזו שנתון סטטיסטי רשמי יכול לאשר או להפריך אותה ישירות ובמדויק.

פסול בהחלט — אל תחלץ: דעות והערכות; אפיון כוונות או מניעים ("היה נוח לצבא לא לגייס", "הממשלה לא מעוניינת"); אמירות עמומות ("קשה להשיג דירה", "המצב חמור"); רטוריקה; הבטחות לעתיד; והצהרות כלליות ללא מספר מדיד. אם אינך בטוח שנתון רשמי יכול לאשר/להפריך את האמירה במדויק — אל תכלול אותה. עדיף להחזיר מערך ריק מאשר טענה רכה.

החזר JSON בלבד — מערך של {{"quote": ציטוט מדויק ומילולי, "topic": הנושא, "claim": הכמות המדויקת שנטענה, "approx_seconds": שנייה}}. אם אין טענה קשיחה כזו — החזר [].

התמלול:
{transcript}"""

_ADJ_PROMPT = """אתה בודק עובדות קפדן. לפניך טענה של פוליטיקאי/ת ונתונים רשמיים מאומתים (כל אחד עם מקור).
סמן "contradicted" או "consistent" אך ורק אם אחד הנתונים שסופקו מודד ישירות את אותה כמות מדויקת שהטענה מתייחסת אליה — כך שהוא באמת מאשר או מפריך אותה.
אם הנתונים רק קשורים לנושא אך אינם מודדים את הכמות הספציפית שנטענה (למשל הטענה על כוונה/קושי/הערכה, או על מדד שונה מזה שסופק) — החזר "unverifiable". התאמה נושאית רופפת אינה מספיקה.
חוק ברזל: השתמש אך ורק במספרים שסופקו. אל תמציא ואל תניח.

הטענה: "{claim}"
ציטוט: "{quote}"

נתונים רשמיים זמינים (index : נתון):
{stats}

החזר JSON: {{"outcome": "contradicted" | "consistent" | "unverifiable", "stat_index": מספר הנתון או null, "confidence": 0..1, "reason": הסבר קצר — וציין במפורש האם הנתון אכן מודד את מה שנטען}}."""


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


def extract_claims(gen, transcript: dict) -> list[dict]:
    """`gen` is a callable(prompt:str) -> parsed JSON (Ollama or Gemini backed)."""
    prompt = _EXTRACT_PROMPT.format(
        topics="\n".join("- " + t for t in TOPICS), transcript=transcript_text(transcript)
    )
    claims = gen(prompt)
    if isinstance(claims, list):
        return claims
    # Some local models wrap the array in an object, e.g. {"claims": [...]}.
    if isinstance(claims, dict):
        for v in claims.values():
            if isinstance(v, list):
                return v
    return []


def adjudicate(gen, claim: str, quote: str, stats: list[dict]) -> dict:
    stat_lines = "\n".join(
        f'{i}: {s.get("metric")} | {s.get("dimension_value","")} = {s.get("value")} {s.get("unit","")} '
        f'({s.get("period","")}) — מקור: {s.get("source_org","")}'
        for i, s in enumerate(stats)
    )
    prompt = _ADJ_PROMPT.format(claim=claim, quote=quote, stats=stat_lines)
    res = gen(prompt)
    return res if isinstance(res, dict) else {"outcome": "unverifiable", "stat_index": None, "confidence": 0, "reason": ""}
