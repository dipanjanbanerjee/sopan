# Sopan — your next step, on time

Sopan checks PhD listings every morning and posts new openings, deadline reminders
and watchlist changes to Telegram. It also publishes an installable web page.
Everything runs free on GitHub.

## What it does each day (07:47 IST)
1. Opens each listing page in `sources.yaml` and picks out the job ads.
2. Keeps the ones that match your keywords (e.g. astronomy + PhD) and reads their deadlines.
3. Posts **new** ones to your Telegram channel, plus **"Closing soon"** reminders 3 days before deadlines.
4. Checks every **watchlist** page and alerts you when a new link appears.
5. Updates the web page (`docs/`).

The very first check of each source only records what is already there (shown on the web page),
so your channel isn't flooded with hundreds of old listings.

## One-time setup (15 minutes)

**1. Telegram channel**
- Create a **public channel**, e.g. `@SopanAlerts`.
- Channel settings → Administrators → add **@SopanAppBot** with permission to post messages.

**2. Secrets** — repo **Settings → Secrets and variables → Actions → New repository secret**
| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token BotFather gave you |
| `TELEGRAM_CHAT_ID` | your channel username, e.g. `@SopanAlerts` |

**3. Web page** — **Settings → Pages** → Source: *Deploy from a branch* → Branch `main`, folder `/docs` → Save.
Your page will be at `https://<your-username>.github.io/sopan/`. Open it on your phone → browser menu → *Add to Home screen*.

**4. First run** — **Actions** tab → *Sopan daily* → *Run workflow*.
Open the run's log: each source prints how many listings it found and matched.
A `⚠️ no listings found` line means that site's URL or `link_pattern` needs adjusting.

After that it runs by itself every morning.

## Change what it watches
Edit `sources.yaml` right on GitHub (pencil icon):
- **Keywords**: add words to `physics_astro` or `phd`.
- **New listing site**: copy a `sources` block, set `url` and a `link_pattern` that every job-ad link contains.
- **Watchlist**: add a professor's or department's "open positions" page under `watch:`.
- Update `site.telegram_url` to your channel link.

## Test on your laptop
```bash
pip install -r requirements.txt
python -m sopan.run --dry-run     # prints what it would post; changes nothing
python -m pytest -q               # runs the tests
```

## If something goes wrong
- **Push fails with "permission denied"**: Settings → Actions → General → Workflow permissions → *Read and write*.
- **Telegram error 403/400**: the bot isn't an admin of the channel, or the chat ID is wrong.
- **Daily runs stopped**: GitHub pauses scheduled runs in repos with no activity for 60 days. Re-enable it in the Actions tab.
- Never put the bot token in any file. It only lives in GitHub Secrets.

## Files
```
sources.yaml              what to check (sites, keywords, watchlist)
sopan/core.py             fetching, link extraction, keyword filter, deadline parsing
sopan/telegram.py         message formatting and sending
sopan/run.py              the daily job
docs/                     the web page (index.html, data.json, icons, offline support)
state/seen.json           what has already been posted (created automatically)
.github/workflows/daily.yml   the free daily schedule
```
