"""Gemini API key pool (free tier) with round-robin rotation + failover.

Three keys rotated round-robin roughly triple the free-tier throughput; on a
rate-limit (HTTP 429) the transcriber advances to the next key and retries.
Keys are loaded from the git-ignored .env (NEVER committed).
"""

from __future__ import annotations

import os
from pathlib import Path

# Env var names checked, in priority order (supports up to 4 keys).
KEY_ENV_NAMES = ["GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4"]


def load_env_file(path: str | Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file. Ignores blanks and # comments."""
    out: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def load_gemini_keys(env: dict[str, str] | None = None) -> list[str]:
    """Collect configured Gemini keys (deduped, blanks skipped), preserving order."""
    env = env if env is not None else dict(os.environ)
    keys: list[str] = []
    for name in KEY_ENV_NAMES:
        v = (env.get(name) or "").strip()
        if v and v not in keys:
            keys.append(v)
    return keys


class GeminiKeyPool:
    """Round-robins across keys; advance() moves to the next (wraps around)."""

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError(
                "No Gemini API keys configured. Set GEMINI_API_KEY[_2/_3] in .env."
            )
        self._keys = list(keys)
        self._i = 0

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def current(self) -> str:
        return self._keys[self._i]

    def advance(self) -> str:
        """Rotate to the next key and return it."""
        self._i = (self._i + 1) % len(self._keys)
        return self.current

    def masked(self) -> list[str]:
        """Safe-to-log fingerprints (never the full secret)."""
        return [f"{k[:6]}…{k[-4:]}" for k in self._keys]
