"""Harvest recent tweets for the 120 MKs (needs an X login — see docs/SETUP_TWEETS.md).

Loads docs/data/mk_handles.json; with --discover (default) it also finds missing
handles by searching each MK's name. Saves tweets to E:\\kn-data\\tweets\\person-<id>.json.
NEVER fabricates — if no X account is configured it just explains how to add one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from knesset_osint.core.console import enable_utf8_console
from knesset_osint.core.logging import configure_logging, get_logger
from knesset_osint.ingestion.tweets import discover_handle, fetch_user_tweets, has_accounts, make_api

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KN_DATA_ROOT", r"E:\kn-data"))
logger = get_logger("worker.tweets")


async def run(args) -> int:
    api = await make_api()
    if not await has_accounts(api):
        print("No X account configured — tweet ingestion is OFF.")
        print("Add one (one-time, ~2 min) — see docs/SETUP_TWEETS.md:")
        print(r"  .venv\Scripts\twscrape add_account <user> <pass> <email> <email_pass>")
        print(r"  .venv\Scripts\twscrape login_accounts")
        return 2

    handles_path = REPO / "docs" / "data" / "mk_handles.json"
    handles = json.loads(handles_path.read_text(encoding="utf-8")).get("handles", {}) if handles_path.exists() else {}
    roster = json.loads((REPO / "docs" / "data" / "mk_roster.json").read_text(encoding="utf-8"))

    if args.discover:
        for r in roster:
            pid = str(r["person_id"])
            if pid in handles:
                continue
            h = await discover_handle(api, r["name"])
            if h:
                handles[pid] = h
                logger.info("discovered @%s for %s", h, r["name"])
            await asyncio.sleep(1.0)
        handles_path.write_text(json.dumps({"schema": 1, "handles": handles}, ensure_ascii=False, indent=2), encoding="utf-8")

    out_dir = DATA / "tweets"
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for pid, handle in handles.items():
        try:
            tw = await fetch_user_tweets(api, handle, limit=args.limit)
            (out_dir / f"person-{pid}.json").write_text(
                json.dumps({"person_id": int(pid), "handle": handle, "tweets": tw}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            total += len(tw)
            print(f"person-{pid} @{handle}: {len(tw)} tweets")
            await asyncio.sleep(1.0)
        except Exception as e:  # noqa: BLE001
            logger.warning("fetch failed @%s: %s", handle, e)
    print(f"done — {total} tweets across {len(handles)} handles")
    return 0


def main() -> int:
    enable_utf8_console()
    configure_logging("INFO")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--discover", action="store_true", default=True, help="discover missing handles by MK name")
    ap.add_argument("--no-discover", dest="discover", action="store_false")
    ap.add_argument("--limit", type=int, default=40, help="tweets per MK")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
