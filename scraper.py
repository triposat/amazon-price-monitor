# scraper.py: Amazon scraper with curl_cffi TLS impersonation + ISP proxy rotation

import json
import re
import random
import time
from datetime import datetime
from itertools import cycle

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_random, retry_if_exception_type
from loguru import logger
from pydantic import BaseModel, Field

from config import PROXIES, REQUEST_TIMEOUT, MAX_RETRIES


class PriceResult(BaseModel):
    asin: str
    title: str
    price: float | None = None
    availability: str = "Unknown"
    rating: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class RetryableError(Exception):
    """Server-side transient error or anti-bot challenge. Worth retrying with a fresh proxy."""


# Primary parser: Amazon embeds a JSON pricing blob in this hidden div on most product pages.
# Format: {"desktop_buybox_group_1": [{"displayPrice": "$24.42", "priceAmount": 24.42, "buyingOptionType": "NEW", ...}]}
# More stable than CSS selectors because Amazon embeds it for their internal "twister" variant-picker JS.
PRICE_JSON_SELECTOR = ".twister-plus-buying-options-price-data"

# Fallback CSS selectors for pages where the JSON blob is missing.
PRICE_SELECTORS = [
    "span.a-price .a-offscreen",
    ".priceToPay .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-offscreen",
]


def extract_price_text(tag):
    if tag is None:
        return None
    text = tag.get_text(strip=True)
    if not text:
        return None
    try:
        return float(text.replace("$", "").replace(",", ""))
    except ValueError:
        return None


class AmazonPriceScraper:
    def __init__(self):
        self._proxy_pool = cycle(PROXIES)

    def _get_next_proxy(self):
        return next(self._proxy_pool).url

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_random(min=3, max=10),
        retry=retry_if_exception_type(RetryableError),  # only retry transient/anti-bot, not 4xx
    )
    def fetch_product_page(self, asin):
        url = f"https://www.amazon.com/dp/{asin}"
        proxy = self._get_next_proxy()

        response = curl_requests.get(
            url, proxy=proxy, timeout=REQUEST_TIMEOUT, impersonate="chrome",
        )

        if response.status_code == 404:
            logger.warning(f"Product {asin} not found (404)")
            return None  # permanent, skip and don't retry

        if response.status_code == 429:
            raise RetryableError(f"Rate limited (429) for {asin}")

        if 500 <= response.status_code < 600:
            raise RetryableError(f"Server error {response.status_code} for {asin}")

        if response.status_code != 200:
            # 4xx other than 404 or 429 (such as 403 Forbidden, 410 Gone). Terminal, no retry.
            raise Exception(f"Permanent HTTP error {response.status_code} for {asin}")

        # Anti-bot detection: Amazon serves multiple block-page variants
        body_lower = response.text.lower()
        if "api-services-support@amazon.com" in response.text:
            raise RetryableError(f"Amazon dog-page CAPTCHA for {asin}")
        if "/errors/validatecaptcha" in body_lower or "type the characters you see" in body_lower:
            raise RetryableError(f"Soft CAPTCHA challenge for {asin}")

        return response.text

    def parse_price_from_json(self, soup):
        """Primary parser: extract price from Amazon's embedded buy-box JSON blob."""
        wrapper = soup.select_one(PRICE_JSON_SELECTOR)
        if wrapper is None:
            return None
        try:
            data = json.loads(wrapper.get_text())
        except (json.JSONDecodeError, ValueError):
            return None

        offers = data.get("desktop_buybox_group_1", [])
        if not offers:
            return None

        # Prefer NEW offers; fall back to the first offer of any other type
        for offer in offers:
            if offer.get("buyingOptionType") == "NEW" and "priceAmount" in offer:
                return float(offer["priceAmount"])
        if "priceAmount" in offers[0]:
            return float(offers[0]["priceAmount"])
        return None

    def parse_price(self, soup):
        # Strategy 1: embedded JSON (most stable)
        price = self.parse_price_from_json(soup)
        if price is not None:
            return price

        # Strategy 2: CSS selector chain
        for selector in PRICE_SELECTORS:
            price = extract_price_text(soup.select_one(selector))
            if price is not None:
                return price

        # Strategy 3: whole + fraction split (older Amazon DOM)
        price_whole = soup.select_one("span.a-price-whole")
        if price_whole:
            whole = price_whole.get_text(strip=True).replace(",", "").rstrip(".")
            frac_tag = soup.select_one("span.a-price-fraction")
            fraction = frac_tag.get_text(strip=True) if frac_tag else "00"
            try:
                return float(f"{whole}.{fraction}")
            except ValueError:
                pass

        # Strategy 4: regex over any .a-offscreen that looks like a dollar amount
        for tag in soup.select(".a-offscreen"):
            text = tag.get_text(strip=True)
            if re.match(r"^\$[\d,]+\.\d{2}$", text):
                price = extract_price_text(tag)
                if price is not None:
                    return price

        return None

    def parse_product_info(self, html, asin):
        soup = BeautifulSoup(html, "lxml")

        title_tag = soup.select_one("#productTitle")
        title = title_tag.get_text(strip=True) if title_tag else "Unknown"

        price = self.parse_price(soup)

        avail_tag = soup.select_one("#availability span")
        if avail_tag is None:
            oos_tag = soup.select_one("#outOfStockBuyBox_feature_div")
            availability = "Out of Stock" if oos_tag else "Unknown"
        else:
            availability = avail_tag.get_text(strip=True)

        rating = None
        rating_tag = soup.select_one("#acrPopover")
        if rating_tag:
            title_attr = rating_tag.get("title", "")
            if isinstance(title_attr, str):
                rating = title_attr.split(" out")[0]

        return PriceResult(
            asin=asin, title=title, price=price,
            availability=availability, rating=rating,
        )

    def get_price(self, asin):
        time.sleep(random.uniform(3, 7))  # human-pacing delay

        try:
            html = self.fetch_product_page(asin)
        except Exception as e:
            logger.error(f"Fetch failed for {asin}: {e}")
            return None

        if html is None:
            return None
        return self.parse_product_info(html, asin)
