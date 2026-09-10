"""Automatic NSE equity universe discovery for the small/micro-cap scanner.

Uses NSE's public equity master for symbols and the quote-equity endpoint for
current price, traded value and market-cap/issued-size fields when available.
Results are cached so a full universe refresh is not performed on every run.
"""

import csv
import io
import json
import os
import time
from typing import Any, Dict, List, Optional

import requests


class NSEUniverse:
    MASTER_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    QUOTE_URL = "https://www.nseindia.com/api/quote-equity"
    HOME_URL = "https://www.nseindia.com"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, cache_dir: str = "./data/universe", request_delay: float = 0.25):
        self.cache_dir = cache_dir
        self.request_delay = request_delay
        os.makedirs(cache_dir, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.initialized = False

    def _init_session(self) -> None:
        if self.initialized:
            return
        try:
            r = self.session.get(self.HOME_URL, timeout=15)
            r.raise_for_status()
            self.initialized = True
        except requests.RequestException as exc:
            raise RuntimeError(f"Could not initialize NSE session: {exc}") from exc

    def symbols(self, include_etfs: bool = False) -> List[str]:
        """Return active NSE equity symbols from the official equity master."""
        response = self.session.get(self.MASTER_URL, timeout=30)
        response.raise_for_status()
        text = response.content.decode("utf-8-sig", errors="replace")
        rows = csv.DictReader(io.StringIO(text))
        result: List[str] = []
        for row in rows:
            symbol = (row.get("SYMBOL") or "").strip().upper()
            series = (row.get("SERIES") or "").strip().upper()
            if not symbol or series != "EQ":
                continue
            if not include_etfs and ("ETF" in symbol or "BEES" in symbol):
                continue
            result.append(symbol)
        return sorted(set(result))

    @staticmethod
    def _first_number(*values: Any) -> Optional[float]:
        for value in values:
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def quote(self, symbol: str) -> Dict[str, Any]:
        self._init_session()
        headers = {"Referer": "https://www.nseindia.com/market-data/live-equity-market"}
        response = self.session.get(self.QUOTE_URL, params={"symbol": symbol}, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        price_info = data.get("priceInfo") or {}
        security_info = data.get("securityInfo") or {}
        metadata = data.get("metadata") or {}
        trade_info = data.get("marketDeptOrderBook") or {}

        price = self._first_number(price_info.get("lastPrice"), data.get("lastPrice"))
        traded_value = self._first_number(
            price_info.get("totalTradedValue"),
            data.get("totalTradedValue"),
            trade_info.get("tradeInfo", {}).get("totalTradedValue"),
        )
        # NSE commonly reports traded value in rupees; normalize to INR crore.
        if traded_value is not None and traded_value > 10000:
            traded_value_cr = traded_value / 1e7
        else:
            traded_value_cr = traded_value

        market_cap = self._first_number(
            data.get("marketCap"),
            security_info.get("marketCap"),
            metadata.get("marketCap"),
        )
        issued_size = self._first_number(
            security_info.get("issuedSize"),
            metadata.get("issuedSize"),
            data.get("issuedSize"),
        )
        # Fallback: issued shares * price. issuedSize is normally in lakhs on NSE.
        if market_cap is None and issued_size is not None and price is not None:
            market_cap = price * issued_size / 100.0  # INR crore

        return {
            "symbol": symbol,
            "company_name": metadata.get("companyName") or data.get("companyName") or symbol,
            "price": price,
            "market_cap_cr": market_cap,
            "avg_daily_value_cr": traded_value_cr,
            "source": "NSE quote-equity",
        }

    def discover(self, limit: Optional[int] = None, refresh: bool = False) -> List[Dict[str, Any]]:
        """Build a current market universe, caching the raw result locally."""
        cache_path = os.path.join(self.cache_dir, "nse_universe.json")
        if os.path.exists(cache_path) and not refresh:
            with open(cache_path, "r", encoding="utf-8") as fh:
                return json.load(fh)

        symbols = self.symbols()
        if limit:
            symbols = symbols[:limit]
        rows: List[Dict[str, Any]] = []
        failures = 0
        for idx, symbol in enumerate(symbols, 1):
            try:
                rows.append(self.quote(symbol))
            except requests.RequestException:
                failures += 1
            except (ValueError, TypeError, KeyError):
                failures += 1
            if idx < len(symbols):
                time.sleep(self.request_delay)

        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "symbols_requested": len(symbols),
            "quote_failures": failures,
            "rows": rows,
        }
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(payload["rows"], fh, indent=2)
        return rows
