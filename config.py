# config.py: loads proxies from environment variable, validates products

import os
from urllib.parse import quote
from pydantic import BaseModel, field_validator


class ProxyConfig(BaseModel):
    host: str
    port: str
    user: str
    password: str

    @property
    def url(self):
        # quote() escapes special characters such as @, :, /, # in the
        # username and password so they do not break the URL structure.
        return f"http://{quote(self.user, safe='')}:{quote(self.password, safe='')}@{self.host}:{self.port}"


class ProductConfig(BaseModel):
    asin: str
    name: str

    @field_validator("asin")
    @classmethod
    def validate_asin(cls, v):
        if len(v) != 10:
            raise ValueError("ASIN must be exactly 10 characters")
        return v


def _load_proxies_from_env():
    """Parse proxies from the PROXIES env var.

    Format: one proxy per line, each line as host:port:user:password.
    The password may contain colons; the split is limited to 4 fields.
    """
    raw = os.environ.get("PROXIES", "").strip()
    if not raw:
        raise RuntimeError(
            "PROXIES env var is empty. Set it as a GitHub Secret with one "
            "host:port:user:password per line."
        )

    proxies = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # split into 4 parts so a colon inside the password is preserved.
        parts = line.split(":", 3)
        if len(parts) != 4:
            raise ValueError(f"Bad proxy line (expected host:port:user:pass): {line}")
        host, port, user, password = parts
        proxies.append(ProxyConfig(host=host, port=port, user=user, password=password))

    if not proxies:
        raise RuntimeError("No valid proxies parsed from PROXIES env var")
    return proxies


PROXIES = _load_proxies_from_env()
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
