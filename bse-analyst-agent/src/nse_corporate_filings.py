"""Live NSE corporate-filing client for governance pre-screening.

Uses NSE's public corporate-announcements and PIT JSON feeds. NSE requires a
browser-like session and cookies for these endpoints, so the client initializes
one session before requesting data. Results are cached locally to reduce load.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from typing import Any

import requests


class NSECorporateFilings:
    HOME_URL = "https://www.nseindia.com"
    ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
    PIT_URL = "https://www.nseindia.com/api/corporates-pit"
    ANNOUNCEMENTS_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    }

    def __init__(self, cache_dir: str = "./data/corporate", request_delay: float = 0.25):
        self.cache_dir = cache_dir
        self.request_delay = request_delay
        os.makedirs(cache_dir, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.initialized = False

    def _init_session(self) -> None:
        if self.initialized:
            return
        response = self.session.get(self.HOME_URL, timeout=20)
        response.raise_for_status()
        self.session.get(self.ANNOUNCEMENTS_PAGE, timeout=20)
        self.initialized = True

    @staticmethod
    def _date(value: date | str | None) -> str:
        if value is None:
            return date.today().strftime("%d-%m-%Y")
        if isinstance(value, date):
            return value.strftime("%d-%m-%Y")
        return str(value)

    def _get_json(self, url: str, params: dict[str, Any]) -> Any:
        self._init_session()
        time.sleep(self.request_delay)
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def announcements(self, symbol: str, days: int = 180) -> list[dict[str, Any]]:
        """Return recent NSE equity announcements for one symbol."""
        end = date.today()
        start = end - timedelta(days=max(1, days))
        data = self._get_json(
            self.ANNOUNCEMENTS_URL,
            {
                "index": "equities",
                "symbol": symbol.upper().strip(),
                "from_date": self._date(start),
                "to_date": self._date(end),
            },
        )
        if isinstance(data, dict):
            data = data.get("data", [])
        return data if isinstance(data, list) else []

    def pit(self, symbol: str, days: int = 365) -> list[dict[str, Any]]:
        """Return recent promoter/director/KMP trading disclosures where available."""
        end = date.today()
        start = end - timedelta(days=max(1, days))
        data = self._get_json(
            self.PIT_URL,
            {
                "index": "equities",
                "symbol": symbol.upper().strip(),
                "from_date": self._date(start),
                "to_date": self._date(end),
            },
        )
        if isinstance(data, dict):
            data = data.get("data", [])
        return data if isinstance(data, list) else []

    def risk_inputs(self, symbol: str, days: int = 180) -> dict[str, Any]:
        """Collect mechanical filing signals for ``corporate_risk.assess_corporate_risk``."""
        announcements = self.announcements(symbol, days=days)
        pit_rows = self.pit(symbol, days=max(days, 365))
        normalized = []
        for row in announcements:
            normalized.append(
                {
                    "subject": row.get("desc") or row.get("subject") or row.get("SUBJECT") or "",
                    "details": row.get("attchmntText") or row.get("details") or row.get("DETAILS") or "",
                    "date": row.get("an_dt") or row.get("dt") or row.get("BROADCAST_DATE") or "",
                }
            )

        pit_flags = []
        for row in pit_rows:
            text = " ".join(str(row.get(k, "")) for k in ("acqMode", "secType", "buySell", "categoryName", "remarks", "symbol"))
            lower = text.lower()
            if any(term in lower for term in ("promoter", "promoter group", "pledge", "encumbrance")):
                pit_flags.append(
                    {
                        "subject": "PIT promoter disclosure",
                        "details": text,
                        "date": row.get("date") or row.get("tradingDate") or "",
                    }
                )

        return {
            "symbol": symbol.upper().strip(),
            "announcements": normalized,
            "pit": pit_rows,
            "pit_risk_rows": pit_flags,
            "source": "NSE corporate-announcements + NSE PIT",
        }

    def cached_risk_inputs(self, symbol: str, days: int = 180, refresh: bool = False) -> dict[str, Any]:
        path = os.path.join(self.cache_dir, f"{symbol.upper().strip()}_filings.json")
        if os.path.exists(path) and not refresh:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        payload = self.risk_inputs(symbol, days=days)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        return payload
