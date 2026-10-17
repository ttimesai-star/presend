"""Thin client for the Blockscout PRO API (REST v2, multichain base URL).

Every request goes to https://api.blockscout.com/{chain_id}/api/v2/... with the key.
The client tracks how many calls were made and the credits left (x-credits-remaining).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

import requests

BASE_URL = "https://api.blockscout.com"
EXPLORERS = {
    1: "https://eth.blockscout.com",
    10: "https://optimism.blockscout.com",
    100: "https://gnosis.blockscout.com",
    8453: "https://base.blockscout.com",
    42161: "https://arbitrum.blockscout.com",
    59144: "https://explorer.linea.build",
    534352: "https://scroll.blockscout.com",
    11155111: "https://eth-sepolia.blockscout.com",
}


class BlockscoutError(RuntimeError):
    pass


def explorer_url(chain_id: int, kind: str, value: str) -> str:
    """Link to Blockscout Explorer: kind is 'address', 'tx' or 'token'."""
    base = EXPLORERS.get(chain_id, f"https://blockscout.com/chain/{chain_id}")
    return f"{base}/{kind}/{value}"


@dataclass
class Usage:
    calls: int = 0
    credits_remaining: int | None = None
    endpoints: dict[str, int] = field(default_factory=dict)


class BlockscoutClient:
    def __init__(self, api_key: str | None = None, chain_id: int = 1,
                 base_url: str = BASE_URL, session: requests.Session | None = None,
                 timeout: float = 30.0, max_retries: int = 4, min_interval: float = 0.22):
        self.api_key = api_key or os.environ.get("BLOCKSCOUT_API_KEY", "")
        if not self.api_key:
            raise BlockscoutError("Blockscout PRO API key missing: set BLOCKSCOUT_API_KEY "
                                  "(free key at https://dev.blockscout.com)")
        self.chain_id = int(chain_id)
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval  # free tier is 5 RPS
        self._last = 0.0
        self.usage = Usage()

    # -- low level -------------------------------------------------------
    def get(self, path: str, **params: Any) -> dict:
        url = f"{self.base_url}/{self.chain_id}/api/v2/{path.lstrip('/')}"
        params = {k: v for k, v in params.items() if v is not None}
        params["apikey"] = self.api_key
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise BlockscoutError(f"network error on {path}: {self._redact(e)}") from None
                time.sleep(1.5 * (attempt + 1))
                continue
            self.usage.calls += 1
            key = path.split("?")[0]
            self.usage.endpoints[key] = self.usage.endpoints.get(key, 0) + 1
            left = r.headers.get("x-credits-remaining")
            if left is not None and str(left).isdigit():
                self.usage.credits_remaining = int(left)
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == self.max_retries:
                    raise BlockscoutError(f"HTTP {r.status_code} on {path}")
                retry_after = str(r.headers.get("Retry-After") or "")
                delay = float(retry_after) if retry_after.isdigit() else 0.5 * 2 ** attempt
                time.sleep(min(delay, 30.0))
                continue
            if r.status_code == 404:
                return {}
            if r.status_code != 200:
                raise BlockscoutError(f"HTTP {r.status_code} on {path}: {self._redact(r.text[:200])}")
            try:
                return r.json()
            except ValueError as e:
                raise BlockscoutError(f"non-JSON answer on {path}") from e
        raise BlockscoutError(f"gave up on {path}")

    def _redact(self, text) -> str:
        """Never let the API key reach an exception message or a log."""
        t = str(text)
        return t.replace(self.api_key, "***") if self.api_key else t

    def pages(self, path: str, max_pages: int = 10, as_of_block: int | None = None,
              hard_cap: int = 60, **params: Any) -> Iterator[dict]:
        """Yield items newest-first across pages (keyset pagination via next_page_params).

        With `as_of_block`, pages that hold only newer items do not count toward `max_pages`
        (they are skipped on the way back in time), up to `hard_cap` requests in total.
        """
        next_params: dict | None = {}
        counted = fetched = 0
        while counted < max_pages and fetched < hard_cap:
            data = self.get(path, **{**params, **(next_params or {})})
            fetched += 1
            items = data.get("items") or []
            newer_only = as_of_block is not None and items and all(
                (_block_of(i) or 0) > as_of_block for i in items)
            if not newer_only:
                counted += 1
            for it in items:
                yield it
            next_params = data.get("next_page_params")
            if not next_params or not items:
                return

    # -- endpoints -------------------------------------------------------
    def address(self, addr: str) -> dict:
        return self.get(f"addresses/{addr}")

    def counters(self, addr: str) -> dict:
        return self.get(f"addresses/{addr}/counters")

    def transactions(self, addr: str, max_pages: int = 6,
                     as_of_block: int | None = None) -> list[dict]:
        return list(self.pages(f"addresses/{addr}/transactions", max_pages, as_of_block))

    def token_transfers(self, addr: str, max_pages: int = 6,
                        as_of_block: int | None = None) -> list[dict]:
        return list(self.pages(f"addresses/{addr}/token-transfers", max_pages, as_of_block))

    def transaction(self, tx_hash: str) -> dict:
        return self.get(f"transactions/{tx_hash}")

    def token(self, token_addr: str) -> dict:
        return self.get(f"tokens/{token_addr}")


def _block_of(item: dict) -> int | None:
    b = item.get("block_number", item.get("block"))
    try:
        return int(b)
    except (TypeError, ValueError):
        return None
