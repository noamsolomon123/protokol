"""YouTube Data API discovery: find interview/speech videos for an MK.

Used by the 24/7 harvester. Search costs 100 quota units each (10,000/day free),
so callers must throttle. Returns lightweight video descriptors; downloading +
transcription happens downstream (we never rehost media).
"""

from __future__ import annotations

import httpx

from knesset_osint.core.logging import get_logger

logger = get_logger("ingestion.discovery")

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_DEFAULT_SUFFIX = "ראיון OR נאום OR מליאה OR ועדה"


def search_mk_videos(
    api_key: str,
    mk_name: str,
    *,
    max_results: int = 6,
    query_suffix: str = _DEFAULT_SUFFIX,
    published_after: str | None = None,
    timeout: float = 30.0,
) -> list[dict]:
    """Return [{video_id, title, channel, published_at}] for an MK (newest first)."""
    params = {
        "key": api_key,
        "part": "snippet",
        "q": f"{mk_name} {query_suffix}",
        "type": "video",
        "order": "date",
        "maxResults": max_results,
        "relevanceLanguage": "he",
        "regionCode": "IL",
    }
    if published_after:
        params["publishedAfter"] = published_after
    r = httpx.get(_SEARCH_URL, params=params, timeout=timeout)
    r.raise_for_status()
    out: list[dict] = []
    for it in r.json().get("items", []):
        vid = (it.get("id") or {}).get("videoId")
        sn = it.get("snippet") or {}
        if vid:
            out.append(
                {
                    "video_id": vid,
                    "title": sn.get("title"),
                    "channel": sn.get("channelTitle"),
                    "published_at": sn.get("publishedAt"),
                }
            )
    return out
