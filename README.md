# Amazon Price Monitor (GitHub Actions edition)

Runs `check_once.py` every 30 minutes via a free GitHub Actions cron schedule.
Stores price history in `price_history.json`, which the workflow auto-commits
back to the repo so state persists between runs.

## Alert policy

A Slack/Discord/email alert fires when **all** of the following are true:

1. Current price is **lower than the lowest price seen in the last 24 hours**
   (a true new daily low, not just a tick down from the last reading)
2. The drop is **at least 2% AND at least $1** in absolute terms (filters out
   noise from cent-level oscillations on cheap items)
3. **No alert has fired for the same product in the last 6 hours** (prevents
   notification spam during volatile periods)

If any check fails, the reading is still stored — you just don't get pinged.

The four thresholds are constants at the top of `check_once.py`:

```python
MIN_DROP_PCT = 2.0
MIN_DROP_DOLLARS = 1.00
COOLDOWN_HOURS = 6
BASELINE_WINDOW_HOURS = 24
HISTORY_RETENTION_DAYS = 30  # auto-prune readings older than this
```

Tweak these to taste. Want every 0.1% drop? Set `MIN_DROP_PCT = 0.1`. Want at most
one alert per product per day? Set `COOLDOWN_HOURS = 24`. Etc.

## File structure

```
.
├── .github/workflows/monitor.yml   # cron schedule + run logic
├── config.py                       # loads proxies from env, validates products
├── scraper.py                      # curl_cffi scraper (TLS impersonation)
├── alerts.py                       # apprise multi-channel alerts (env-driven)
├── check_once.py                   # entry point — single-shot price check
├── products.json                   # ASINs to monitor + target prices
├── requirements.txt
├── .gitignore
└── price_history.json              # auto-created by first run
```

## Setup (one-time, ~10 minutes)

### 1. Create a new private GitHub repo

Don't make it public — `price_history.json` will be committed automatically
and you probably don't want your purchasing patterns indexed by Google.

### 2. Push these files to it

```bash
cd path/to/this/folder
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin git@github.com:YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### 3. Add two GitHub Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**.

**Secret 1: `PROXIES`** — one proxy per line, format `host:port:user:password`:

```
69.54.248.46:59544:your_user:your_pass
69.54.250.138:58372:your_user:your_pass
69.54.250.14:65040:your_user:your_pass
...
```

**Secret 2: `APPRISE_URLS`** — one notification channel per line. Pick at least one:

```
discord://webhook_id/webhook_token
tgram://bot_token/chat_id
mailto://you:app_password@gmail.com?to=you@gmail.com
```

Full list of supported channel URL formats:
https://github.com/caronc/apprise/wiki

### 4. Edit `products.json`

Replace the example ASINs with the products you actually care about. Each entry:

```json
{"asin": "B07MHJFRBJ", "name": "Friendly name", "target_price": 22.00}
```

Commit and push.

### 5. Trigger the first run manually

Go to the **Actions** tab → **Amazon Price Monitor** → **Run workflow**. This
verifies your secrets are set correctly. Subsequent runs happen automatically
every 30 minutes.

## Caveats worth knowing

- **GitHub schedule precision is loose.** Cron triggers can be delayed by
  10–30 minutes during high load. For price monitoring this is fine; for
  flash-deal hunting you'd want a dedicated server.
- **Scheduled workflows pause after 60 days of repo inactivity.** The auto-commits
  this workflow makes count as activity, so this won't bite you in practice.
- **GitHub free tier gives 2,000 Actions minutes/month for private repos.**
  Each run takes ~1 minute. 48 runs/day × 30 days = ~1,440 minutes — comfortably
  under the limit, with headroom for retries. (Public repos: unlimited.)
- **Concurrency lock** in the workflow prevents two runs from racing on
  `price_history.json` if a long-running check overlaps with the next schedule.

## Editing what's monitored

Just edit `products.json` and push. The next scheduled run picks up the new list
automatically. No deploy step.

## Adjusting cadence

In `.github/workflows/monitor.yml`, change the cron:

```yaml
- cron: "*/15 * * * *"   # every 15 minutes
- cron: "0 * * * *"       # every hour
- cron: "0 */6 * * *"     # every 6 hours
```

## Troubleshooting

- **Workflow run failed** → click the run, expand the failed step, read the log.
  Most failures are missing/malformed `PROXIES` or `APPRISE_URLS` secrets.
- **No alerts firing even with target hits** → check `APPRISE_URLS` is set and
  your notification channel is live (test it manually with `apprise -vv -t "test" -b "body" "your-url"`).
- **Workflow stuck "queued"** → GitHub free runners are sometimes slow during
  peak hours; usually clears in 5–15 minutes.
