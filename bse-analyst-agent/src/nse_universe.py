"""Automatic NSE equity universe discovery for the small/micro-cap scanner.

Uses NSE's public equity master for symbols. For live price/liquidity/market-cap
fields, NSE's quote-equity endpoint is attempted first, but the scanner also
supports a bulk Yahoo Finance quote fallback because NSE may return HTTP 403
to automated quote requests. The fallback avoids thousands of sequential calls.
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
    YAHOO_QUOTE_URLS = (
        "https://query1.finance.yahoo.com/v7/finance/quote",
        "https://query2.finance.yahoo.com/v7/finance/quote",
    )
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
        """Initialize an NSE web session when the homepage is accessible.

        NSE can return HTTP 403 to automated clients. Callers should treat this
        as a provider-unavailable condition and use the bulk fallback.
        """
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
        """Fetch one quote from Yahoo Finance as a fallback provider."""
        data = self._yahoo_quotes([symbol])
        if symbol not in data:
            raise requests.RequestException(f"No Yahoo quote returned for {symbol}")
        return data[symbol]

    def _yahoo_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch quotes in batches to avoid one HTTP request per NSE symbol."""
        result: Dict[str, Dict[str, Any]] = {}
        yahoo_symbols = ",".join(self._yahoo_symbol(symbol) for symbol in symbols)
        last_error: Optional[Exception] = None

        for url in self.YAHOO_QUOTE_URLS:
            try:
                response = self.session.get(
                    url,
                    params={"symbols": yahoo_symbols},
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()
                quotes = (payload.get("quoteResponse") or {}).get("result") or []
                for quote in quotes:
                    yahoo_symbol = str(quote.get("symbol") or "")
                    if not yahoo_symbol.endswith(".NS"):
                        continue
                    symbol = yahoo_symbol[:-3]
                    price = self._first_number(
                        quote.get("regularMarketPrice"),
                        quote.get("postMarketPrice"),
                    )
                    traded_value = self._first_number(quote.get("regularMarketVolume"))
                    market_cap = self._first_number(quote.get("marketCap"))
                    result[symbol] = {
                        "symbol": symbol,
                        "company_name": quote.get("longName") or quote.get("shortName") or symbol,
                        "price": price,
                        "market_cap_cr": market_cap / 1e7 if market_cap is not None else None,
                        "avg_daily_value_cr": None,
                        "volume": traded_value,
                        "source": "Yahoo Finance quote fallback",
                    }
                return result
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                last_error = exc

        raise requests.RequestException(f"Yahoo quote fallback failed: {last_error}")

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
        """Build a current market universe using bulk quote fallback when needed."""
        cache_path = os.path.join(self.cache_dir, "nse_universe.json")
        if os.path.exists(cache_path) and not refresh:
            with open(cache_path, "r", encoding="utf-8") as fh:
                return json.load(fh)

        symbols = self.symbols()
        if limit:
            symbols = symbols[:limit]

        rows: List[Dict[str, Any]] = []
        failures = 0
        batch_size = 50
        for start in range(0, len(symbols), batch_size):
            batch = symbols[start:start + batch_size]
            try:
                batch_rows = self._yahoo_quotes(batch)
                for symbol in batch:
                    row = batch_rows.get(symbol)
                    if row is not None:
                        rows.append(row)
                    else:
                        failures += 1
            except requests.RequestException:
                # If Yahoo bulk quotes fail, fall back to individual provider attempts.
                for symbol in batch:
                    try:
                        rows.append(self.quote(symbol))
                    except (requests.RequestException, RuntimeError, ValueError, TypeError, KeyError):
                        failures += 1
                    time.sleep(self.request_delay)
            if start + batch_size < len(symbols):
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
