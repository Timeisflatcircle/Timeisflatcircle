"""Automatic NSE equity universe discovery for the small/micro-cap scanner.

Uses NSE's public equity master for symbols. Live price/liquidity comes from
NSE when available and Yahoo Finance chart otherwise. Market cap is separated
into a bulk, TTL-based cache so a full universe scan does not make one market-
cap request per symbol.
"""

import csv
import io
import json
import os
import time
from typing import Any, Dict, List, Optional

import requests

from src.market_cap_cache import MarketCapCache


class NSEUniverse:
    MASTER_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    QUOTE_URL = "https://www.nseindia.com/api/quote-equity"
    HOME_URL = "https://www.nseindia.com"
    YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
    YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
    YAHOO_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary"
    YAHOO_COOKIE_URL = "https://fc.yahoo.com"
    YAHOO_CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, cache_dir: str = "./data/universe", request_delay: float = 0.25,
                 market_cap_cache: Optional[MarketCapCache] = None):
        self.cache_dir = cache_dir
        self.request_delay = request_delay
        os.makedirs(cache_dir, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.initialized = False
        self.yahoo_crumb: Optional[str] = None
        self.market_cap_cache = market_cap_cache or MarketCapCache(
            cache_path=os.path.join(cache_dir, "market_caps.json"),
            request_delay=request_delay,
        )

    def _init_session(self) -> None:
        if self.initialized:
            return
        try:
            r = self.session.get(self.HOME_URL, timeout=15)
            r.raise_for_status()
            self.initialized = True
        except requests.RequestException as exc:
            raise RuntimeError(f"NSE quote session unavailable: {exc}") from exc

    def _init_yahoo_auth(self, force: bool = False) -> None:
        if self.yahoo_crumb and not force:
            return
        self.yahoo_crumb = None
        cookie_response = self.session.get(self.YAHOO_COOKIE_URL, headers={"Referer": "https://finance.yahoo.com/"}, timeout=15)
        if cookie_response.status_code not in (200, 404):
            cookie_response.raise_for_status()
        crumb_response = self.session.get(self.YAHOO_CRUMB_URL, headers={"Referer": "https://finance.yahoo.com/"}, timeout=15)
        crumb_response.raise_for_status()
        crumb = crumb_response.text.strip()
        if not crumb or "Unauthorized" in crumb:
            raise requests.RequestException("Yahoo Finance returned an invalid crumb")
        self.yahoo_crumb = crumb

    def symbols(self, include_etfs: bool = False) -> List[str]:
        response = self.session.get(self.MASTER_URL, timeout=30)
        response.raise_for_status()
        text = response.content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        reader.fieldnames = [field.strip().upper() if field else field for field in (reader.fieldnames or [])]
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
        data = self._yahoo_quotes([symbol])
        if symbol not in data:
            raise requests.RequestException(f"No Yahoo chart quote returned for {symbol}")
        return data[symbol]

    def _yahoo_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for symbol in symbols:
            url = f"{self.YAHOO_CHART_URL}/{self._yahoo_symbol(symbol)}"
            response = self.session.get(url, params={"range": "1d", "interval": "1d"}, timeout=20)
            response.raise_for_status()
            payload = response.json()
            chart_results = (payload.get("chart") or {}).get("result") or []
            if not chart_results:
                continue
            data = chart_results[0]
            meta = data.get("meta") or {}
            price = self._first_number(meta.get("regularMarketPrice"), meta.get("previousClose"), meta.get("chartPreviousClose"))
            volume = self._first_number(meta.get("regularMarketVolume"))
            if volume is None:
                quote_rows = ((data.get("indicators") or {}).get("quote") or [])
                if quote_rows:
                    for value in reversed(quote_rows[0].get("volume") or []):
                        if value is not None:
                            volume = self._first_number(value)
                            break
            traded_value_cr = price * volume / 1e7 if price is not None and volume is not None else None
            result[symbol] = {
                "symbol": symbol,
                "company_name": meta.get("longName") or meta.get("shortName") or symbol,
                "price": price,
                "market_cap_cr": None,
                "avg_daily_value_cr": traded_value_cr,
                "volume": volume,
                "source": "Yahoo Finance chart fallback",
            }
        return result

    def _yahoo_market_caps(self, symbols: List[str], batch_size: int = 100) -> Dict[str, float]:
        if not symbols:
            return {}
        self._init_yahoo_auth()
        result: Dict[str, float] = {}
        for start in range(0, len(symbols), batch_size):
            batch = symbols[start:start + batch_size]
            yahoo_symbols = [self._yahoo_symbol(symbol) for symbol in batch]
            response = self.session.get(self.YAHOO_QUOTE_URL, params={"symbols": ",".join(yahoo_symbols), "crumb": self.yahoo_crumb}, headers={"Referer": "https://finance.yahoo.com/"}, timeout=30)
            if response.status_code in (401, 403):
                self._init_yahoo_auth(force=True)
                response = self.session.get(self.YAHOO_QUOTE_URL, params={"symbols": ",".join(yahoo_symbols), "crumb": self.yahoo_crumb}, headers={"Referer": "https://finance.yahoo.com/"}, timeout=30)
            response.raise_for_status()
            for quote in ((response.json().get("quoteResponse") or {}).get("result") or []):
                yahoo_symbol = quote.get("symbol")
                market_cap = self._first_number(quote.get("marketCap"))
                if yahoo_symbol and yahoo_symbol.endswith(".NS") and market_cap is not None:
                    result[yahoo_symbol[:-3]] = market_cap / 1e7
            if start + batch_size < len(symbols):
                time.sleep(self.request_delay)
        return result

    def _yahoo_market_cap_summary(self, symbol: str) -> Optional[float]:
        self._init_yahoo_auth()
        url = f"{self.YAHOO_SUMMARY_URL}/{self._yahoo_symbol(symbol)}"
        params = {"modules": "price,summaryDetail,defaultKeyStatistics", "crumb": self.yahoo_crumb}
        headers = {"Referer": "https://finance.yahoo.com/"}
        response = self.session.get(url, params=params, headers=headers, timeout=30)
        if response.status_code in (401, 403):
            self._init_yahoo_auth(force=True)
            params["crumb"] = self.yahoo_crumb
            response = self.session.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        rows = ((response.json().get("quoteSummary") or {}).get("result") or [])
        if not rows:
            return None
        result = rows[0]
        for section in (result.get("price") or {}, result.get("summaryDetail") or {}, result.get("defaultKeyStatistics") or {}):
            value = section.get("marketCap") if isinstance(section, dict) else None
            if isinstance(value, dict):
                value = value.get("raw")
            value = self._first_number(value)
            if value is not None:
                return value / 1e7
        return None

    def quote(self, symbol: str, market_cap_override: Optional[float] = None) -> Dict[str, Any]:
        symbol = symbol.strip().upper()
        try:
            self._init_session()
            response = self.session.get(
                self.QUOTE_URL,
                params={"symbol": symbol},
                headers={"Referer": "https://www.nseindia.com/market-data/live-equity-market"},
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            price_info = data.get("priceInfo") or {}
            security_info = data.get("securityInfo") or {}
            metadata = data.get("metadata") or {}
            trade_info = data.get("marketDeptOrderBook") or {}
            price = self._first_number(price_info.get("lastPrice"), data.get("lastPrice"))
            traded_value = self._first_number(price_info.get("totalTradedValue"), data.get("totalTradedValue"), trade_info.get("tradeInfo", {}).get("totalTradedValue"))
            traded_value_cr = traded_value / 1e7 if traded_value is not None and traded_value > 10000 else traded_value
            market_cap = self._first_number(data.get("marketCap"), security_info.get("marketCap"), metadata.get("marketCap"))
            issued_size = self._first_number(security_info.get("issuedSize"), metadata.get("issuedSize"), data.get("issuedSize"))
            if market_cap is None and issued_size is not None and price is not None:
                market_cap = price * issued_size / 100.0
            used_cache = market_cap is None and market_cap_override is not None
            if used_cache:
                market_cap = market_cap_override
            return {
                "symbol": symbol,
                "company_name": metadata.get("companyName") or data.get("companyName") or symbol,
                "price": price,
                "market_cap_cr": market_cap,
                "avg_daily_value_cr": traded_value_cr,
                "source": "NSE quote-equity + market-cap cache" if used_cache else "NSE quote-equity",
            }
        except (requests.RequestException, RuntimeError):
            quote = self._yahoo_quote(symbol)
            if market_cap_override is not None:
                quote["market_cap_cr"] = market_cap_override
                quote["source"] = "Yahoo Finance chart + market-cap cache"
                return quote
            market_cap_source = None
            try:
                market_caps = self._yahoo_market_caps([symbol])
                quote["market_cap_cr"] = market_caps.get(symbol)
                market_cap_source = "Yahoo Finance quote"
            except requests.RequestException:
                try:
                    quote["market_cap_cr"] = self._yahoo_market_cap_summary(symbol)
                    market_cap_source = "Yahoo Finance quoteSummary"
                except requests.RequestException:
                    quote["market_cap_cr"] = None
            quote["source"] = f"Yahoo Finance chart + {market_cap_source} fallback" if quote["market_cap_cr"] is not None else "Yahoo Finance chart fallback (market cap unavailable)"
            return quote

    def discover(self, limit: Optional[int] = None, refresh: bool = False) -> List[Dict[str, Any]]:
        cache_path = os.path.join(self.cache_dir, "nse_universe.json")
        if os.path.exists(cache_path) and not refresh:
            with open(cache_path, "r", encoding="utf-8") as fh:
                return json.load(fh)

        symbols = self.symbols()
        if limit:
            symbols = symbols[:limit]

        market_caps = self.market_cap_cache.ensure_fresh(symbols)
        rows: List[Dict[str, Any]] = []
        failures = 0
        for idx, symbol in enumerate(symbols, 1):
            try:
                cached = market_caps.get(symbol, {}).get("market_cap_cr")
                override = float(cached) if cached is not None else None
                rows.append(self.quote(symbol, market_cap_override=override))
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
