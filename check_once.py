# check_once.py — single-shot price check, designed to be invoked by cron/GitHub Actions
#
# Alert policy: notify on ANY price drop vs. the most recent prior reading.
# No target prices — even a $0.01 drop fires an alert.

import sys
import json
from loguru import logger
from pydantic import TypeAdapter
from tinydb import TinyDB, Query
from scraper import AmazonPriceScraper
from config import ProductConfig
from alerts import send_alert


logger.remove()
logger.add(sys.stderr, format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}")


ProductList = TypeAdapter(list[ProductConfig])


def get_prior_price(db, asin):
    """Return the most recent prior price for this ASIN, or None if no history."""
    P = Query()
    history = db.search(P.asin == asin)
    if not history:
        return None
    # Timestamps are ISO 8601 strings, so lexical sort = chronological sort
    most_recent = max(history, key=lambda r: r.get("timestamp", ""))
    return most_recent.get("price")


def main():
    with open("products.json") as f:
        data = json.load(f)
    products = ProductList.validate_python(data["products"])

    logger.info(f"Checking {len(products)} products")

    db = TinyDB("price_history.json")
    scraper = AmazonPriceScraper()

    successes = 0
    failures = 0
    drops = 0

    for product in products:
        result = scraper.get_price(product.asin)

        if not (result and result.price is not None):
            logger.warning(f"Failed to get price for {product.name} ({product.asin})")
            failures += 1
            continue

        current = result.price
        prior_price = get_prior_price(db, product.asin)

        # Insert this reading AFTER querying prior (so we don't compare against ourselves)
        db.insert(result.model_dump(mode="json"))
        successes += 1

        if prior_price is None:
            logger.info(f"{product.name} — ${current:.2f} (first reading, baseline established)")
        elif current < prior_price:
            drop = prior_price - current
            pct = (drop / prior_price) * 100
            logger.success(
                f"PRICE DROP! {product.name}: "
                f"${prior_price:.2f} → ${current:.2f} "
                f"(-${drop:.2f}, -{pct:.2f}%)"
            )
            send_alert(result, product, prior_price)
            drops += 1
        elif current > prior_price:
            rise = current - prior_price
            logger.info(
                f"{product.name} — ${current:.2f} "
                f"(up ${rise:.2f} from ${prior_price:.2f}, no alert)"
            )
        else:
            logger.info(f"{product.name} — ${current:.2f} (no change)")

    logger.info(
        f"Cycle done. {successes} ok, {failures} failed, {drops} price drop(s) alerted."
    )

    if successes == 0 and failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
