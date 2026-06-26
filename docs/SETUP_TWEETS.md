# Activating tweet ingestion (one-time, ~2 minutes)

X (Twitter) has **no free, no-login API** in 2026 (Nitter is gutted, the official
API is paid). So the tweet pipeline needs **one X account** to read public tweets
via `twscrape`. Use a **throwaway / secondary** X account — there is a small ban
risk for automated reading.

### Steps (run from the repo root: `C:\Users\noams\knesset-osint`)

1. **Add your X account:**
   ```
   .venv\Scripts\twscrape add_account <username> <password> <email> <email_password>
   ```
2. **Log it in** (solves the auth flow once):
   ```
   .venv\Scripts\twscrape login_accounts
   ```
3. **Harvest tweets** (auto-discovers each MK's handle by name, then pulls recent tweets):
   ```
   .venv\Scripts\python.exe scripts\worker_tweets.py
   ```

Tweets are saved to `E:\kn-data\tweets\person-<id>.json`. The MK→handle map lives
in `docs\data\mk_handles.json` (auto-filled by discovery; you can also edit it by
hand). Re-run the worker any time to refresh.

**Integrity:** we never fabricate tweets — without a configured account the worker
simply prints these instructions and exits.

### Make it part of the 24/7 loop (optional)
Add a scheduled run of `worker_tweets.py` (e.g., every few hours) the same way the
interview harvester runs via `run_harvester.bat` + a Startup shortcut.
