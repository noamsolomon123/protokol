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


class RotatingYouTubeSearch:
    """Search across several YouTube API keys, round-robin, with quota failover.

    Each Google project key has its own 10,000 units/day budget, so N keys give N
    independent budgets. We rotate per call and, on a 403 (quota exhausted / key
    disabled), advance to the next key and retry the same query — only raising if
    every key is exhausted. ``search_fn`` is injectable for testing.
    """

    def __init__(self, keys: list[str], *, search_fn=search_mk_videos) -> None:
        if not keys:
            raise ValueError("RotatingYouTubeSearch needs at least one API key.")
        self._keys = list(keys)
        self._i = 0
        self._search = search_fn

    def __len__(self) -> int:
        return len(self._keys)

    def __call__(self, mk_name: str, **kw) -> list[dict]:
        n = len(self._keys)
        last_403: Exception | None = None
        for off in range(n):
            key = self._keys[(self._i + off) % n]
            try:
                res = self._search(key, mk_name, **kw)
            except httpx.HTTPStatusError as e:  # quota (403) -> try the next key
                if e.response is not None and e.response.status_code == 403:
                    last_403 = e
                    logger.warning("YouTube key #%d quota/403 — failing over.", (self._i + off) % n)
                    continue
                raise
            self._i = (self._i + off + 1) % n  # next call starts on the following key
            return res
        if last_403 is not None:
            raise last_403  # all keys exhausted this round
        return []
