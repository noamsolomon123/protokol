"""Tests for RotatingYouTubeSearch — round-robin across keys with quota failover.
No network: the underlying search is faked.
"""

from __future__ import annotations

import httpx
import pytest

from knesset_osint.ingestion.discovery import DEEP_QUERY_PLAN, RotatingYouTubeSearch, deep_search


def _http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://www.googleapis.com/youtube/v3/search")
    return httpx.HTTPStatusError("err", request=req, response=httpx.Response(status, request=req))


def test_round_robin_advances_keys():
    used: list[str] = []

    def fake(key, name, **kw):
        used.append(key)
        return [{"video_id": "v"}]

    s = RotatingYouTubeSearch(["k1", "k2", "k3"], search_fn=fake)
    for q in "abcd":
        s(q)
    assert used == ["k1", "k2", "k3", "k1"]  # wraps around


def test_failover_on_403_quota():
    def fake(key, name, **kw):
        if key == "dead":
            raise _http_error(403)
        return [{"video_id": "ok"}]

    s = RotatingYouTubeSearch(["dead", "live"], search_fn=fake)
    assert s("x") == [{"video_id": "ok"}]  # 403 on 'dead' -> fail over to 'live'


def test_failover_on_429_ratelimit():
    def fake(key, name, **kw):
        if key == "limited":
            raise _http_error(429)
        return [{"video_id": "ok"}]

    s = RotatingYouTubeSearch(["limited", "live"], search_fn=fake)
    assert s("x") == [{"video_id": "ok"}]  # 429 on 'limited' -> fail over to 'live'


def test_all_keys_exhausted_raises_403():
    def fake(key, name, **kw):
        raise _http_error(403)

    s = RotatingYouTubeSearch(["a", "b"], search_fn=fake)
    with pytest.raises(httpx.HTTPStatusError):
        s("x")


def test_non_403_error_propagates_immediately():
    def fake(key, name, **kw):
        raise _http_error(500)

    s = RotatingYouTubeSearch(["a", "b"], search_fn=fake)
    with pytest.raises(httpx.HTTPStatusError):
        s("x")


def test_requires_at_least_one_key():
    with pytest.raises(ValueError):
        RotatingYouTubeSearch([])


# --- F9 deeper crawl: deep_search ---

def test_deep_search_runs_every_combo_and_dedupes():
    seen_combos: list[tuple] = []

    def fake(name, *, max_results, query_suffix, order, **kw):
        seen_combos.append((query_suffix, order))
        tag = f"{order}:{query_suffix[:4]}"
        return [{"video_id": "shared"}, {"video_id": tag}]

    res = deep_search(fake, "מישהו", combo_delay=0)
    ids = [v["video_id"] for v in res]
    assert len(seen_combos) == len(DEEP_QUERY_PLAN)        # every combo issued
    assert ids.count("shared") == 1                         # deduped to one
    assert len(res) == 1 + len(set(seen_combos))            # shared + one unique per distinct combo


def test_deep_search_skips_failing_combo():
    def fake(name, *, max_results, query_suffix, order, **kw):
        if order == "viewCount":
            raise httpx.HTTPStatusError("quota", request=httpx.Request("GET", "http://x"),
                                        response=httpx.Response(403))
        return [{"video_id": order}]

    res = deep_search(fake, "X", combo_delay=0)
    ids = {v["video_id"] for v in res}
    assert "viewCount" not in ids                           # failing combo skipped
    assert "date" in ids and "relevance" in ids             # others still returned


def test_deep_search_passes_order_through_real_signature():
    # the real search_mk_videos accepts order=; deep_search must call with it
    captured = []

    def fake(name, *, max_results, query_suffix, order, **kw):
        captured.append(order)
        return []

    deep_search(fake, "X", plan=[("a", "date"), ("b", "viewCount")], combo_delay=0)
    assert captured == ["date", "viewCount"]


def test_deep_search_paces_between_combos():
    sleeps: list[float] = []
    def fake(name, *, max_results, query_suffix, order, **kw):
        return []
    plan = [("a", "date"), ("b", "relevance"), ("c", "viewCount")]
    deep_search(fake, "X", plan=plan, combo_delay=1.2, _sleep=lambda s: sleeps.append(s))
    assert sleeps == [1.2, 1.2]  # paced between combos: N-1 sleeps, none before the first
