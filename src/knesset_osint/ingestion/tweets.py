"""Twitter/X tweet ingestion via twscrape (requires a configured X login).

There is NO free, no-login way to read X in 2026 (Nitter is gutted, the official
API is paid). twscrape reads X's GraphQL using a logged-in account that the user
adds ONCE (see docs/SETUP_TWEETS.md). Until an account is added, the worker
reports that clearly and does nothing. We never fabricate tweets.
"""

from __future__ import annotations

from knesset_osint.core.logging import get_logger

logger = get_logger("ingestion.tweets")


async def make_api():
    from twscrape import API

    return API()  # accounts stored in ./accounts.db


async def has_accounts(api) -> bool:
    try:
        accts = await api.pool.accounts_info()
    except Exception:  # noqa: BLE001
        return False
    return bool(accts) and any(a.get("active") for a in accts)


async def discover_handle(api, mk_name: str) -> str | None:
    """Best-effort: search X users by the MK's name and return the top handle."""
    try:
        from twscrape import gather

        users = await gather(api.search_user(mk_name, limit=3))
        return users[0].username if users else None
    except Exception as e:  # noqa: BLE001
        logger.warning("handle discovery failed for %s: %s", mk_name, e)
        return None


async def fetch_user_tweets(api, handle: str, *, limit: int = 40) -> list[dict]:
    """Return recent tweets for a handle: [{id, date, text, url, likes, retweets}]."""
    from twscrape import gather

    user = await api.user_by_login(handle)
    if not user:
        return []
    tweets = await gather(api.user_tweets(user.id, limit=limit))
    out: list[dict] = []
    for t in tweets:
        out.append({
            "id": str(t.id),
            "date": t.date.isoformat() if getattr(t, "date", None) else None,
            "text": getattr(t, "rawContent", None),
            "url": getattr(t, "url", None),
            "likes": getattr(t, "likeCount", None),
            "retweets": getattr(t, "retweetCount", None),
        })
    return out
