"""Tests for RotatingYouTubeSearch — round-robin across keys with quota failover.
No network: the underlying search is faked.
"""

from __future__ import annotations

import httpx
import pytest

from knesset_osint.ingestion.discovery import RotatingYouTubeSearch


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
