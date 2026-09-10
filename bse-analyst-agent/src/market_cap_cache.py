"""Bulk, cached market-cap reference data for the NSE universe.

Market cap is intentionally separated from per-symbol quote calls. The cache is
refreshed in Yahoo Finance batches and persisted with source/as-of metadata so
scanners do not request market cap 2,000+ times on every run.
"""

import json
import os
import time
from typing import Dict, List, Optional

import requests


class MarketCapCache:
    YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
    YAHOO_COOKIE_URL = "https://fc.yahoo.com"
    YAHOO_CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
    DEFAULT_CACHE_PATH = "./data/universe/market_caps.json"
    DEFAULT_TTL_HOURS = 24
    DEFAULT_BATCH_SIZE = 100
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }

    def __init__(
        self,
        cache_path: Optional[str] = None,
        ttl_hours: Optional[float] = None,
        batch_size: Optional[int] = None,
        request_delay: float = 0.25,
    ):
        self.cache_path = cache_path or os.getenv("MARKET_CAP_CACHE_PATH", self.DEFAULT_CACHE_PATH)
        self.ttl_hours = float(os.getenv("MARKET_CAP_CACHE_TTL_HOURS", self.DEFAULT_TTL_HOURS)) if ttl_hours is None else float(ttl_hours)
        self.batch_size = int(os.getenv("MARKET_CAP_BATCH_SIZE", self.DEFAULT_BATCH_SIZE)) if batch_size is None else int(batch_size)
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.crumb: Optional[str] = None

    @staticmethod
    def _symbol(symbol: str) -> str:
        return f"{symbol.strip().upper()}.NS"

    def _auth(self, force: bool = False) -> None:
        if self.crumb and not force:
            return
        self.crumb = None
        cookie = self.session.get(self.YAHOO_COOKIE_URL, headers={"Referer": "https://finance.yahoo.com/"}, timeout=15)
        if cookie.status_code not in (200, 404):
            cookie.raise_for_status()
        crumb = self.session.get(self.YAHOO_CRUMB_URL, headers={"Referer": "https://finance.yahoo.com/"}, timeout=15)
        crumb.raise_for_status()
        value = crumb.text.strip()
        if not value or "Unauthorized" in value:
            raise requests.RequestException("Yahoo Finance returned an invalid crumb")
        self.crumb = value

    def _load(self) -> Dict[str, Dict[str, object]]:
        if not os.path.exists(self.cache_path):
            return {}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            return payload.get("data", {}) if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save(self, data: Dict[str, Dict[str, object]]) -> None:
        os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "ttl_hours": self.ttl_hours,
            "source": "Yahoo Finance quote endpoint",
            "data": data,
        }
        tmp = f"{self.cache_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        os.replace(tmp, self.cache_path)

    def _fetch_batch(self, symbols: List[str]) -> Dict[str, Dict[str, object]]:
        self._auth()
        yahoo_symbols = [self._symbol(s) for s in symbols]
        params = {"symbols": ",".join(yahoo_symbols), "crumb": self.crumb}
        response = self.session.get(
            self.YAHOO_QUOTE_URL,
            params=params,
            headers={"Referer": "https://finance.yahoo.com/"},
            timeout=30,
        )
        if response.status_code in (401, 403):
            self._auth(force=True)
            params["crumb"] = self.crumb
            response = self.session.get(
                self.YAHOO_QUOTE_URL,
                params=params,
                headers={"Referer": "https://finance.yahoo.com/"},
                timeout=30,
            )
        response.raise_for_status()
        rows = ((response.json().get("quoteResponse") or {}).get("result") or [])
        result: Dict[str, Dict[str, object]] = {}
        for row in rows:
            yahoo_symbol = row.get("symbol")
            market_cap = row.get("marketCap")
            if not yahoo_symbol or not yahoo_symbol.endswith(".NS") or market_cap is None:
                continue
            try:
                value_cr = float(market_cap) / 1e7
            except (TypeError, ValueError):
                continue
            symbol = yahoo_symbol[:-3]
            result[symbol] = {
                "market_cap_cr": value_cr,
                "as_of": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source": "Yahoo Finance quote endpoint",
            }
        return result

    def refresh(self, symbols: List[str]) -> Dict[str, Dict[str, object]]:
        """Refresh market caps in batches and persist the complete cache."""
        symbols = sorted({s.strip().upper() for s in symbols if s and s.strip()})
        data = self._load()
        for start in range(0, len(symbols), self.batch_size):
            batch = symbols[start:start + self.batch_size]
            try:
                data.update(self._fetch_batch(batch))
            except requests.RequestException:
                # Keep older cached values rather than inventing a value.
                pass
            if start + self.batch_size < len(symbols):
                time.sleep(self.request_delay)
        self._save(data)
        return data

    def get(self, symbol: str, refresh_if_stale: bool = False, universe: Optional[List[str]] = None) -> Optional[float]:
        """Return cached market cap in INR crore; optionally refresh stale cache."""
        key = symbol.strip().upper()
        data = self._load()
        row = data.get(key)
        if row:
            try:
                age_hours = (time.time() - time.mktime(time.strptime(row["as_of"], "%Y-%m-%dT%H:%M:%S"))) / 3600
                if age_hours <= self.ttl_hours:
                    return float(row["market_cap_cr"])
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
        if refresh_if_stale and universe:
            data = self.refresh(universe)
            row = data.get(key)
            if row:
                return float(row["market_cap_cr"])
        return None
