# Amazon Price Monitor

A scheduled price monitor that runs `check_once.py` every 30 minutes on free
GitHub Actions. Each run adds new results to `price_history.json`, and the
workflow commits this file back to the repository so the history is preserved
between runs.

## Alert thresholds

The workflow sends an alert (to Slack, Discord, email, or any other supported
channel) when **all** of the following conditions are true:

1. The current price is **lower than the lowest price recorded in the last
   24 hours**. This is a new 24-hour low, not a small change from the previous
   reading.
2. The drop is **at least 2% and at least $1**. This filters out small changes
   of a few cents on low-cost items.
3. **No alert has been sent for the same product in the last 6 hours.** This
   prevents repeated notifications when prices change often.

If any condition fails, the script still saves the reading to history but does
not send a notification.

These three limits, plus the history retention setting, are defined as
constants near the top of `check_once.py`:

```python
MIN_DROP_PCT = 2.0
MIN_DROP_DOLLARS = 1.00
COOLDOWN_HOURS = 6
BASELINE_WINDOW_HOURS = 24
HISTORY_RETENTION_DAYS = 30  # readings older than this are deleted automatically
```

Adjust these values to change the alert behavior. For example:

- To alert on any drop of 0.1% or larger, set `MIN_DROP_PCT = 0.1`.
- To allow at most one alert per product per day, set `COOLDOWN_HOURS = 24`.

## File structure

```
.
├── .github/workflows/monitor.yml   # cron schedule and run logic
├── config.py                       # loads proxies from environment, validates products
├── scraper.py                      # curl_cffi scraper (TLS impersonation)
├── alerts.py                       # Apprise multi-channel alerts (configured via env)
├── check_once.py                   # entry point: runs one price check per execution
├── products.json                   # list of ASINs to monitor (asin and name fields only)
├── requirements.txt
├── .gitignore
└── price_history.json              # created automatically on the first run
```

## Setup (one-time, about 10 minutes)

Fork this repository (or clone it locally) so you have the starter files. Then follow these steps to configure your own copy.

### 1. Create a private GitHub repository

Use a private repository, not a public one. The workflow commits
`price_history.json` automatically, which records the products you monitor and
their price changes over time. A private repository keeps this data out of
search engine indexes.

### 2. Push these files to the repository

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

In your repository, go to **Settings → Secrets and variables → Actions → New repository secret**, then add the following two secrets.

**Secret 1: `PROXIES`**

One proxy per line, in the format `host:port:user:password`:

```
proxy1.example.com:8000:your_user:your_pass
proxy2.example.com:8001:your_user:your_pass
proxy3.example.com:8002:your_user:your_pass
...
```

**Secret 2: `APPRISE_URLS`**

One notification channel URL per line. At least one channel is required:

```
discord://webhook_id/webhook_token
tgram://bot_token/chat_id
mailto://you:app_password@gmail.com?to=you@gmail.com
```

For the full list of supported notification channels and their URL formats, see the Apprise wiki:
https://github.com/caronc/apprise/wiki

### 4. Edit `products.json`

Replace the example ASINs with the products you want to monitor. Each entry
needs two fields: `asin` and a recognizable `name`:

```json
{"asin": "B07MHJFRBJ", "name": "Bounty Paper Towels"}
```

There is no target price field. An alert is sent when a price drop crosses the
thresholds defined in `check_once.py`. Commit and push your changes when you
are done.

### 5. Trigger the first run manually

Open the **Actions** tab in your repository, select **Amazon Price Monitor**,
and click **Run workflow**. This first run confirms that your secrets are
configured correctly. After this, runs happen automatically every 30 minutes.

## Important limitations

- **Scheduled runs are not exact.** GitHub may delay cron triggers by 10 to 30
  minutes during periods of high load. For routine price monitoring this is
  acceptable. For time-sensitive cases such as flash sales, use a dedicated
  server instead.
- **GitHub pauses workflows after 60 days of repository inactivity.** This
  workflow's automatic commits count as activity, so the schedule does not
  pause in normal use.
- **The GitHub free tier provides 2,000 Actions minutes per month for private
  repositories.** Each run takes about 1 minute. With 48 runs per day across
  30 days, monthly usage is about 1,440 minutes, which is below the free tier
  limit. Public repositories have unlimited minutes.
- **The workflow includes a concurrency lock.** This prevents two runs from
  writing to `price_history.json` at the same time. Without the lock, this
  could happen when a slow run overlaps with the next scheduled run.

## Changing the monitored products

Edit `products.json` and push the change to the repository. The next scheduled
run will use the updated list. No additional deployment step is required.

## Changing the run frequency

Edit the `cron` value in `.github/workflows/monitor.yml`:

```yaml
- cron: "*/15 * * * *"   # every 15 minutes
- cron: "0 * * * *"      # every hour
- cron: "0 */6 * * *"    # every 6 hours
```

## Troubleshooting

- **The workflow run failed.** Open the failed run in the Actions tab, expand
  the failed step, and read the log output. Most failures are caused by a
  missing or incorrectly formatted `PROXIES` or `APPRISE_URLS` secret.
- **No alerts are sent even when prices drop.** Confirm that `APPRISE_URLS` is
  configured and that your notification channel is working. You can test the
  channel from the command line:

  ```bash
  apprise -vv -t "test" -b "body" "your-url"
  ```

  Also verify that the price drop crosses the thresholds in `check_once.py`.
  For example, a $0.10 drop on a $30 item is below the default 2% threshold
  and will not trigger an alert.
- **The workflow is stuck in the "queued" state.** GitHub's free runners can
  be delayed during periods of high demand. The queue typically clears within
  5 to 15 minutes.
