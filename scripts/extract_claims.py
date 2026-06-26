"""Extract checkable factual claims from a transcript (on topics we have official
stats for), using Gemini. Produces candidate claims for the verdict step.

    .venv\\Scripts\\python.exe scripts/extract_claims.py <transcript.json>
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from knesset_osint.core.console import enable_utf8_console
from knesset_osint.ingestion.transcription.keys import GeminiKeyPool, load_env_file, load_gemini_keys
from knesset_osint.verification.gemini_llm import gemini_generate_json

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))

# Topics where we have adversarially-verified official statistics (Phase 3).
TOPICS = [
    'גיוס לצה"ל ושיעורי גיוס (כללי / חרדים / מגזרים)',
    "יוקר המחיה ואינפלציה (מדד המחירים לצרכן)",
    "אבטלה, תעסוקה ושכר",
    "מחירי דיור ושכר דירה",
    "פשיעה וביטחון אישי",
    "עוני ואי-שוויון",
]

PROMPT = """לפניך תמלול של דברי פוליטיקאי/ת ישראלי/ת. יש לנו נתונים רשמיים לבדיקה אך ורק על הנושאים הבאים:
{topics}

המשימה: חלץ כל אמירה עובדתית הניתנת לבדיקה שהפוליטיקאי/ת אמר/ה ושקשורה לאחד הנושאים האלה — אמירה עם מספר, אחוז, השוואה, סופרלטיב ("הכי", "הנמוך/הגבוה ביותר"), או מגמה ("עלה", "ירד", "הוכפל") שניתן לאשר או להפריך מול נתון רשמי.
התעלם מ: דעות, הבטחות לעתיד, הצהרות כלליות, וכל מה שאינו ניתן לבדיקה מול נתון.
החזר JSON תקין בלבד — מערך של אובייקטים: {{"quote": הציטוט המדויק מהתמלול, "topic": הנושא מהרשימה, "claim": תקציר הטענה במשפט, "approx_seconds": שנייה משוערת מתחילת הראיון}}. אם אין אמירות כאלה כלל, החזר [].

התמלול:
{transcript}"""


def _transcript_text(d: dict, max_chars: int = 14000) -> str:
    return " ".join(s.get("text", "") for s in d.get("segments", []))[:max_chars]


def extract_from_transcript(pool: GeminiKeyPool, d: dict, model: str) -> list[dict]:
    prompt = PROMPT.format(topics="\n".join("- " + t for t in TOPICS), transcript=_transcript_text(d))
    claims = gemini_generate_json(pool, prompt, model=model)
    return claims if isinstance(claims, list) else []


def main() -> int:
    enable_utf8_console()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("transcript")
    ap.add_argument("--model", default="gemini-2.5-flash")
    args = ap.parse_args()

    for k, v in load_env_file(REPO / ".env").items():
        os.environ.setdefault(k, v)
    pool = GeminiKeyPool(load_gemini_keys())

    src = Path(args.transcript)
    d = json.loads(src.read_text(encoding="utf-8"))
    claims = extract_from_transcript(pool, d, args.model)

    print(f"{d.get('mk_name')} — {str(d.get('title',''))[:55]} -> {len(claims)} checkable claim(s)")
    for c in claims[:12]:
        print(f"  [{c.get('approx_seconds','?')}s] ({str(c.get('topic',''))[:22]}) {str(c.get('quote',''))[:100]}")

    out_dir = DATA / "claims" / src.parent.name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{src.stem}.json").write_text(
        json.dumps(
            {"source": str(src), "mk_name": d.get("mk_name"), "person_id": d.get("person_id"),
             "video_id": d.get("video_id"), "url": d.get("url"), "claims": claims},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
