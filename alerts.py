# alerts.py — multi-channel alerts via apprise, configured from env

import os
import apprise
from loguru import logger
from scraper import PriceResult
from config import ProductConfig

notifier = apprise.Apprise()

# Each line in APPRISE_URLS is one apprise notification URL.
# Examples:
#   slack://TokenA/TokenB/TokenC
#   discord://webhook_id/webhook_token
#   tgram://bot_token/chat_id
#   mailto://user:app_password@gmail.com?to=you@gmail.com
# Full list: https://github.com/caronc/apprise/wiki
for url in os.environ.get("APPRISE_URLS", "").strip().splitlines():
    url = url.strip()
    if url:
        notifier.add(url)


def send_alert(result: PriceResult, product: ProductConfig, prior_price: float):
    """Send a price-drop alert. Caller has already verified current < prior."""
    drop = prior_price - result.price
    pct = (drop / prior_price) * 100

    title = f"Price Drop: {product.name}"
    body = (
        f"{result.title}\n\n"
        f"Previous: ${prior_price:.2f}\n"
        f"Current:  ${result.price:.2f}\n"
        f"Drop:     ${drop:.2f} (-{pct:.2f}%)\n"
        f"\nhttps://www.amazon.com/dp/{result.asin}\n"
    )

    if len(notifier) > 0:
        notifier.notify(title=title, body=body)
        logger.success(
            f"Alert sent for {result.asin} — ${result.price:.2f} (was ${prior_price:.2f})"
        )
    else:
        logger.warning(f"No notification services configured! {title}")
