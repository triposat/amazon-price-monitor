# check_once.py — single-shot price check, designed to be invoked by cron/GitHub Actions

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


def main():
    with open("products.json") as f:
        data = json.load(f)
    products = ProductList.validate_python(data["products"])

    logger.info(f"Checking {len(products)} products")

    db = TinyDB("price_history.json")
    P = Query()
    scraper = AmazonPriceScraper()

    successes = 0
    failures = 0
    target_hits = 0

    for product in products:
        result = scraper.get_price(product.asin)

        if result and result.price is not None:
            db.insert(result.model_dump(mode="json"))

            history = db.search(P.asin == product.asin)
            prices = [r["price"] for r in history if r["price"]]

            current = result.price
            lowest = min(prices)
            highest = max(prices)

            if current <= product.target_price:
                logger.success(
                    f"TARGET HIT! {product.name} — ${current:.2f} "
                    f"(target: ${product.target_price:.2f})"
                )
                send_alert(result, product)
                target_hits += 1
            else:
                logger.info(
                    f"{product.name} — ${current:.2f} "
                    f"(low: ${lowest:.2f}, high: ${highest:.2f})"
                )
            successes += 1
        else:
            logger.warning(f"Failed to get price for {product.name} ({product.asin})")
            failures += 1

    logger.info(
        f"Cycle done. {successes} ok, {failures} failed, "
        f"{target_hits} target(s) hit."
    )

    # Non-zero exit if every product failed — surfaces as a red workflow run
    if successes == 0 and failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
