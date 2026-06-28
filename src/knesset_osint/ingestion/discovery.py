"""YouTube Data API discovery: find interview/speech videos for an MK.

Used by the 24/7 harvester. Search costs 100 quota units each (10,000/day free),
so callers must throttle. Returns lightweight video descriptors; downloading +
transcription happens downstream (we never rehost media).
"""

from __future__ import annotations

import time

import httpx

from knesset_osint.core.logging import get_logger

logger = get_logger("ingestion.discovery")

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_DEFAULT_SUFFIX = "ראיון OR נאום OR מליאה OR ועדה"

# F9 deeper crawl: the single date-ordered query saturates at the recent ~25 videos
# per MK. Running several (suffix, order) combos and deduping surfaces a much larger,
# more historical pool — relevance/viewCount return different top sets than date, and
# varied phrasings catch interviews the default query misses. Each combo is one search
# (100 quota units), so this trades breadth-per-MK for MKs-per-pass; appropriate now
# that the recent corpus is saturated. None suffix = the bare name.
DEEP_QUERY_PLAN: list[tuple[str | None, str]] = [
    (_DEFAULT_SUFFIX, "date"),                 # the original pass (newest)
    ("ראיון OR ראיון מלא OR בראיון", "relevance"),
    ("נאום OR דברים OR הצהרה OR מסיבת עיתונאים", "relevance"),
    ("ראיון OR נאום OR ועדה", "viewCount"),    # most-watched (older, popular)
    (None, "relevance"),                       # bare name, relevance
]


def search_mk_videos(
    api_key: str,
    mk_name: str,
    *,
    max_results: int = 6,
    query_suffix: str = _DEFAULT_SUFFIX,
    order: str = "date",
    published_after: str | None = None,
    timeout: float = 30.0,
) -> list[dict]:
    """Return [{video_id, title, channel, published_at}] for an MK.

    ``order`` is the YouTube sort: 'date' (newest, default — unchanged behaviour),
    'relevance', or 'viewCount'. Varying it surfaces different result sets (F9).
    """
    params = {
        "key": api_key,
        "part": "snippet",
        "q": f"{mk_name} {query_suffix}".strip(),
        "type": "video",
        "order": order,
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
        last_err: Exception | None = None
        for off in range(n):
            key = self._keys[(self._i + off) % n]
            try:
                res = self._search(key, mk_name, **kw)
            except httpx.HTTPStatusError as e:  # quota (403) / rate-limit (429) -> try the next key
                if e.response is not None and e.response.status_code in (403, 429):
                    last_err = e
                    logger.warning("YouTube key #%d %s — failing over.",
                                   (self._i + off) % n, e.response.status_code)
                    continue
                raise
            self._i = (self._i + off + 1) % n  # next call starts on the following key
            return res
        if last_err is not None:
            raise last_err  # all keys exhausted / rate-limited this round
        return []


def deep_search(
    search,
    mk_name: str,
    *,
    plan: list[tuple[str | None, str]] = DEEP_QUERY_PLAN,
    max_results: int = 25,
    combo_delay: float = 1.2,
    _sleep=time.sleep,
    **kw,
) -> list[dict]:
    """F9 deeper crawl: run every (suffix, order) combo in ``plan`` through ``search``
    (a RotatingYouTubeSearch — so key rotation/quota failover is reused) and dedupe by
    video id. A combo that fails (e.g. all keys exhausted) is skipped, so we still
    return whatever the other combos found. Newest-first combos run first, so the
    deduped order roughly preserves recency.

    ``combo_delay`` paces the combos (default 1.2s) so the burst of N requests per MK
    doesn't trip YouTube's short-window rate limit (429). It runs in the discovery
    thread only, so it never blocks transcription. ``_sleep`` is injectable for tests."""
    seen: dict[str, dict] = {}
    for i, (suffix, order) in enumerate(plan):
        if i and combo_delay:
            _sleep(combo_delay)
        try:
            res = search(mk_name, max_results=max_results, query_suffix=(suffix or ""), order=order, **kw)
        except Exception as e:  # quota exhausted / transient — keep what we have
            logger.warning("deep_search combo (%s / %s) failed: %s", suffix, order, e)
            continue
        for v in res:
            vid = v.get("video_id")
            if vid and vid not in seen:
                seen[vid] = v
    return list(seen.values())
