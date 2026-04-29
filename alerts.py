# alerts.py: multi-channel alerts via apprise, configured from environment variable

import os
import apprise
from loguru import logger
from scraper import PriceResult
from config import ProductConfig

notifier = apprise.Apprise()

# Each line in APPRISE_URLS is one apprise notification URL. Examples:
#   slack://TokenA/TokenB/TokenC
#   discord://webhook_id/webhook_token
#   tgram://bot_token/chat_id
#   mailto://user:app_password@gmail.com?to=you@gmail.com
# See https://github.com/caronc/apprise/wiki for the full list of services.
for url in os.environ.get("APPRISE_URLS", "").strip().splitlines():
    url = url.strip()
    if url:
        notifier.add(url)


def send_alert(result: PriceResult, product: ProductConfig, prior_price: float):
    """Send a price-drop alert. The caller has already verified current < prior."""
    # Documents the contract and silences type checkers about None price.
    assert result.price is not None, "send_alert requires a non-None result.price"

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
        # Apprise returns False when delivery fails. Without this check, a
        # broken webhook would still log success and the failure would be silent.
        if notifier.notify(title=title, body=body):
            logger.success(
                f"Alert sent for {result.asin}: ${result.price:.2f} (was ${prior_price:.2f})"
            )
        else:
            logger.error(
                f"Alert delivery failed for {result.asin}: ${result.price:.2f} (was ${prior_price:.2f})"
            )
    else:
        logger.warning(f"No notification services configured! {title}")
