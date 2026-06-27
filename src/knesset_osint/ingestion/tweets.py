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


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isalnum()).lower()


# Bio keywords that mark a real Knesset/public-figure account (Hebrew + English).
_MK_BIO_KW = (
    "כנסת", 'ח"כ', "ח״כ", "חבר הכנסת", "חברת הכנסת", "חבר כנסת", "סגן שר",
    "שר ", "שרת ", "סיעת", "מפלגת", "knesset", "member of knesset", "mk,",
)


async def discover_handle(api, mk_name: str) -> str | None:
    """Search X users by the MK's name and return a VERIFIED handle, or None.

    Integrity gate: we never attribute tweets to a wrong/parody account. A match
    is accepted only if the candidate's display name matches the MK's name AND the
    account looks like a public figure — a Knesset/minister bio, a government/verified
    badge, or a substantial following.
    """
    from twscrape import gather

    try:
        users = await gather(api.search_user(mk_name, limit=5))
    except Exception as e:  # noqa: BLE001
        logger.warning("handle discovery failed for %s: %s", mk_name, e)
        return None

    target = _norm(mk_name)
    if not target:
        return None
    for u in users:
        dn = _norm(getattr(u, "displayname", "") or "")
        bio = (getattr(u, "rawDescription", "") or "").lower()
        followers = getattr(u, "followersCount", 0) or 0
        gov = getattr(u, "blueType", "") == "Government" or bool(getattr(u, "verified", False))
        name_match = bool(dn) and (target in dn or dn in target)
        if name_match and (any(k.lower() in bio for k in _MK_BIO_KW) or gov or followers >= 5000):
            return getattr(u, "username", None)
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
