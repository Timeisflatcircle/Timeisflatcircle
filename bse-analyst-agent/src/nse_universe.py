"""Automatic NSE equity universe discovery for the small/micro-cap scanner.

Uses NSE's public equity master for symbols. For live price/liquidity/market-cap
fields, NSE's quote-equity endpoint is attempted first, but the scanner also
supports a Yahoo Finance chart fallback because NSE and Yahoo quote endpoints
may reject automated quote requests. The chart endpoint provides current price
and volume without the Yahoo quote-endpoint authentication flow.
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
    YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
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
        """Initialize an NSE web session when the homepage is accessible."""
        if self.initialized:
            return
        try:
            r = self.session.get(self.HOME_URL, timeout=15)
            r.raise_for_status()
            self.initialized = True
        except requests.RequestException as exc:
            raise RuntimeError(f"NSE quote session unavailable: {exc}") from exc

    def symbols(self, include_etfs: bool = False) -> List[str]:
        """Return active NSE equity symbols from the official equity master."""
        response = self.session.get(self.MASTER_URL, timeout=30)
        response.raise_for_status()
        text = response.content.decode("utf-8-sig", errors="replace")

        # NSE's CSV currently contains whitespace in some header names
        # (e.g. `` SERIES``). Normalize headers so field lookup is stable.
        reader = csv.DictReader(io.StringIO(text))
        reader.fieldnames = [
            field.strip().upper() if field else field
            for field in (reader.fieldnames or [])
        ]

        result: List[str] = []
        for row in reader:
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

    @staticmethod
    def _yahoo_symbol(symbol: str) -> str:
        return f"{symbol}.NS"

    def _yahoo_quote(self, symbol: str) -> Dict[str, Any]:
        """Fetch one current quote from Yahoo Finance's chart endpoint."""
        data = self._yahoo_quotes([symbol])
        if symbol not in data:
            raise requests.RequestException(f"No Yahoo chart quote returned for {symbol}")
        return data[symbol]

    def _yahoo_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch current price/volume using Yahoo's chart endpoint.

        Yahoo's /v7/finance/quote endpoint now commonly returns 401 without
        its authentication/crumb flow, while /v8/finance/chart exposes the
        current market price and volume in the chart metadata.
        """
        result: Dict[str, Dict[str, Any]] = {}
        for symbol in symbols:
            yahoo_symbol = self._yahoo_symbol(symbol)
            url = f"{self.YAHOO_CHART_URL}/{yahoo_symbol}"
            response = self.session.get(
                url,
                params={"range": "1d", "interval": "1d"},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            chart = payload.get("chart") or {}
            chart_results = chart.get("result") or []
            if not chart_results:
                continue

            data = chart_results[0]
            meta = data.get("meta") or {}
            price = self._first_number(
                meta.get("regularMarketPrice"),
                meta.get("previousClose"),
                meta.get("chartPreviousClose"),
            )
            volume = None
            indicators = data.get("indicators") or {}
            quote_rows = indicators.get("quote") or []
            if quote_rows:
                volumes = quote_rows[0].get("volume") or []
                for value in reversed(volumes):
                    if value is not None:
                        volume = self._first_number(value)
                        break

            traded_value_cr = (
                price * volume / 1e7
                if price is not None and volume is not None
                else None
            )
            result[symbol] = {
                "symbol": symbol,
                "company_name": meta.get("longName") or meta.get("shortName") or symbol,
                "price": price,
                # Yahoo chart does not expose market cap. Keep this explicitly
                # unknown rather than inventing a value.
                "market_cap_cr": None,
                "avg_daily_value_cr": traded_value_cr,
                "volume": volume,
                "source": "Yahoo Finance chart fallback",
            }
        return result

    def quote(self, symbol: str) -> Dict[str, Any]:
        """Fetch one quote, falling back when NSE blocks automated access."""
        symbol = symbol.strip().upper()
        try:
            self._init_session()
            headers = {"Referer": "https://www.nseindia.com/market-data/live-equity-market"}
            response = self.session.get(
                self.QUOTE_URL,
                params={"symbol": symbol},
                headers=headers,
                timeout=20,
            )
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
            traded_value_cr = traded_value / 1e7 if traded_value is not None and traded_value > 10000 else traded_value
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
            if market_cap is None and issued_size is not None and price is not None:
                market_cap = price * issued_size / 100.0

            return {
                "symbol": symbol,
                "company_name": metadata.get("companyName") or data.get("companyName") or symbol,
                "price": price,
                "market_cap_cr": market_cap,
                "avg_daily_value_cr": traded_value_cr,
                "source": "NSE quote-equity",
            }
        except (requests.RequestException, RuntimeError):
            return self._yahoo_quote(symbol)

    def discover(self, limit: Optional[int] = None, refresh: bool = False) -> List[Dict[str, Any]]:
        """Build a current market universe using quote fallback when needed."""
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
            except (requests.RequestException, RuntimeError, ValueError, TypeError, KeyError):
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
