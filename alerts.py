# alerts.py — multi-channel alerts via apprise, configured from env

import os
import apprise
from loguru import logger
from scraper import PriceResult
from config import ProductConfig

notifier = apprise.Apprise()

# Each line in APPRISE_URLS is one apprise notification URL.
# Examples:
#   discord://webhook_id/webhook_token
#   tgram://bot_token/chat_id
#   mailto://user:app_password@gmail.com?to=you@gmail.com
#   slack://token_a/token_b/token_c/#channel
# Full list: https://github.com/caronc/apprise/wiki
for url in os.environ.get("APPRISE_URLS", "").strip().splitlines():
    url = url.strip()
    if url:
        notifier.add(url)


def send_alert(result: PriceResult, product: ProductConfig):
    title = f"Price Drop: {result.title[:50]}"
    body = (
        f"Product: {result.title}\n"
        f"Current Price: ${result.price:.2f}\n"
        f"Target Price: ${product.target_price:.2f}\n"
        f"You Save: ${product.target_price - result.price:.2f}\n"
        f"\nhttps://www.amazon.com/dp/{result.asin}\n"
    )

    if len(notifier) > 0:
        notifier.notify(title=title, body=body)
        logger.success(f"Alert sent for {result.asin} — ${result.price:.2f}")
    else:
        logger.warning(f"No notification services configured! Price alert: {title}")
