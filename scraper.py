# scraper.py — Amazon scraper with curl_cffi TLS impersonation + ISP proxy rotation

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_random, retry_if_exception_type
from loguru import logger
from pydantic import BaseModel, Field
from datetime import datetime
from itertools import cycle
import re
import random
import time
from config import PROXIES, REQUEST_TIMEOUT, MAX_RETRIES


class PriceResult(BaseModel):
    asin: str
    title: str
    price: float | None = None
    availability: str = "Unknown"
    rating: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


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
        retry=retry_if_exception_type(Exception),
    )
    def fetch_product_page(self, asin):
        url = f"https://www.amazon.com/dp/{asin}"
        proxy = self._get_next_proxy()

        response = curl_requests.get(
            url, proxy=proxy, timeout=REQUEST_TIMEOUT, impersonate="chrome",
        )

        if response.status_code == 404:
            logger.warning(f"Product {asin} not found (404)")
            return None

        if response.status_code != 200:
            raise Exception(f"Status {response.status_code} for {asin}")

        if "captcha" in response.text.lower() or "api-services-support@amazon.com" in response.text:
            logger.warning(f"CAPTCHA detected for {asin}, retrying...")
            raise Exception(f"CAPTCHA for {asin}")

        return response.text

    def parse_price(self, soup):
        for selector in PRICE_SELECTORS:
            price = extract_price_text(soup.select_one(selector))
            if price is not None:
                return price

        price_whole = soup.select_one("span.a-price-whole")
        if price_whole:
            whole = price_whole.get_text(strip=True).replace(",", "").rstrip(".")
            frac_tag = soup.select_one("span.a-price-fraction")
            fraction = frac_tag.get_text(strip=True) if frac_tag else "00"
            try:
                return float(f"{whole}.{fraction}")
            except ValueError:
                pass

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
        time.sleep(random.uniform(3, 7))

        try:
            html = self.fetch_product_page(asin)
        except Exception as e:
            logger.error(f"All retries failed for {asin}: {e}")
            return None

        if html is None:
            return None
        return self.parse_product_info(html, asin)
