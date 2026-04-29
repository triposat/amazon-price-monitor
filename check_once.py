# check_once.py: single-shot price check, designed to be invoked by cron/GitHub Actions
#
# Alert policy:
#   Fire a Slack alert when current price is a new low vs. the last 24 hours
#   AND the drop is meaningful (>= 2% AND >= $1)
#   AND we haven't already alerted on this product in the last 6 hours.
#
# Tune the constants below to taste.

import sys
import json
from datetime import datetime, timedelta
from loguru import logger
from pydantic import TypeAdapter
from tinydb import TinyDB, Query
from scraper import AmazonPriceScraper
from config import ProductConfig
from alerts import send_alert


# ─── Tunable thresholds ────────────────────────────────────────────────
MIN_DROP_PCT = 2.0          # only alert on drops >= 2% from baseline
MIN_DROP_DOLLARS = 1.00     # AND >= $1 absolute (whichever is tighter wins)
COOLDOWN_HOURS = 6          # don't re-alert on the same product within 6h
BASELINE_WINDOW_HOURS = 24  # baseline = lowest price seen in last 24h
HISTORY_RETENTION_DAYS = 30 # auto-delete readings older than 30 days
# ───────────────────────────────────────────────────────────────────────


logger.remove()
logger.add(sys.stderr, format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}")

ProductList = TypeAdapter(list[ProductConfig])


def prune_old_entries(db, retention_days=HISTORY_RETENTION_DAYS):
    """Delete readings older than retention_days. Keeps file size bounded."""
    P = Query()
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
    removed = db.remove(P.timestamp < cutoff)
    if removed:
        logger.info(f"Pruned {len(removed)} entries older than {retention_days}d")


def get_baseline_price(db, asin, window_hours=BASELINE_WINDOW_HOURS):
    """Lowest price for this ASIN in the last `window_hours`, or None if no recent data."""
    P = Query()
    cutoff = (datetime.now() - timedelta(hours=window_hours)).isoformat()
    recent = db.search((P.asin == asin) & (P.timestamp >= cutoff))
    prices = [r["price"] for r in recent if r.get("price") is not None]
    return min(prices) if prices else None


def get_last_alert_time(db, asin):
    """Timestamp of the most recent reading we alerted on for this ASIN, or None."""
    P = Query()
    alerted = db.search((P.asin == asin) & (P.alerted == True))  # noqa: E712
    if not alerted:
        return None
    most_recent = max(alerted, key=lambda r: r.get("timestamp", ""))
    return datetime.fromisoformat(most_recent["timestamp"])


def decide(current, baseline, last_alert_at, now):
    """Pure function: return (should_alert, reason_string)."""
    if baseline is None:
        return False, "no recent baseline (re-establishing)"

    if current >= baseline:
        if current == baseline:
            return False, f"matches 24h low (${baseline:.2f})"
        return False, f"above 24h low ${baseline:.2f}"

    drop = baseline - current
    pct = (drop / baseline) * 100

    if drop < MIN_DROP_DOLLARS or pct < MIN_DROP_PCT:
        return False, (
            f"drop -${drop:.2f}/-{pct:.2f}% below threshold "
            f"(need >=${MIN_DROP_DOLLARS:.2f} AND >={MIN_DROP_PCT}%)"
        )

    if last_alert_at is not None:
        hours_since = (now - last_alert_at).total_seconds() / 3600
        if hours_since < COOLDOWN_HOURS:
            return False, (
                f"cooldown active ({hours_since:.1f}h since last alert, "
                f"need {COOLDOWN_HOURS}h)"
            )

    return True, f"new 24h low (was ${baseline:.2f}, drop -${drop:.2f}/-{pct:.2f}%)"


def main():
    with open("products.json") as f:
        data = json.load(f)
    products = ProductList.validate_python(data["products"])

    logger.info(f"Checking {len(products)} products")

    db = TinyDB("price_history.json")
    prune_old_entries(db)
    scraper = AmazonPriceScraper()
    now = datetime.now()

    successes = failures = drops_alerted = drops_suppressed = 0

    for product in products:
        result = scraper.get_price(product.asin)

        if not (result and result.price is not None):
            logger.warning(f"Failed to get price for {product.name} ({product.asin})")
            failures += 1
            continue

        current = result.price
        baseline = get_baseline_price(db, product.asin)
        last_alert_at = get_last_alert_time(db, product.asin)

        should_alert, reason = decide(current, baseline, last_alert_at, now)

        record = result.model_dump(mode="json")
        record["alerted"] = should_alert
        db.insert(record)
        successes += 1

        if should_alert:
            assert baseline is not None  # decide() guarantees this when should_alert=True
            logger.success(
                f"PRICE DROP! {product.name}: ${current:.2f} | {reason}"
            )
            send_alert(result, product, baseline)
            drops_alerted += 1
        elif baseline is not None and current < baseline:
            # Drop occurred but was suppressed by threshold/cooldown
            logger.info(f"{product.name}: ${current:.2f} | suppressed: {reason}")
            drops_suppressed += 1
        else:
            logger.info(f"{product.name}: ${current:.2f} | {reason}")

    logger.info(
        f"Cycle done. {successes} ok, {failures} failed, "
        f"{drops_alerted} alert(s) sent, {drops_suppressed} drop(s) suppressed."
    )

    if successes == 0 and failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
