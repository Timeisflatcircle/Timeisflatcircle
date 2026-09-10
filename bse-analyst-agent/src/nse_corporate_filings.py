"""Live NSE corporate-filing client for governance pre-screening.

Uses NSE's public corporate-announcements, PIT, and shareholding-pattern feeds.
NSE endpoints can intermittently return 403/timeouts, so the client warms the
public filing pages first and converts temporary access failures into explicit
DATA_GAP results instead of crashing the scanner.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from typing import Any

import requests
from requests import RequestException


class NSECorporateFilings:
    HOME_URL = "https://www.nseindia.com"
    ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
    PIT_URL = "https://www.nseindia.com/api/corporates-pit"
    SHAREHOLDING_URL = "https://www.nseindia.com/api/corporate-share-holdings-master"
    ANNOUNCEMENTS_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
    SHAREHOLDING_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Referer": ANNOUNCEMENTS_PAGE,
    }

    def __init__(self, cache_dir: str = "./data/corporate", request_delay: float = 0.5):
        self.cache_dir = cache_dir
        self.request_delay = request_delay
        os.makedirs(cache_dir, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.initialized = False

    def _init_session(self) -> None:
        if self.initialized:
            return

        # The public filing pages are a more reliable bootstrap than the NSE
        # homepage for this client. They also establish the cookies used by
        # the filing API endpoints.
        for page in (self.ANNOUNCEMENTS_PAGE, self.SHAREHOLDING_PAGE):
            response = self.session.get(
                page,
                headers={"Referer": self.HOME_URL + "/"},
                timeout=30,
            )
            response.raise_for_status()

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
        response = self.session.get(
            url,
            params=params,
            headers={"Referer": self.ANNOUNCEMENTS_PAGE},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _rows(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, dict):
            data = data.get("data", [])
        return data if isinstance(data, list) else []

    @staticmethod
    def _find_number(row: dict[str, Any], names: tuple[str, ...]) -> float | None:
        """Find a numeric field despite NSE/XBRL naming variations."""
        wanted = {name.lower().replace("_", "") for name in names}

        def walk(value: Any) -> float | None:
            if not isinstance(value, dict):
                return None
            for key, item in value.items():
                normalized = str(key).lower().replace("_", "")
                if normalized in wanted:
                    try:
                        return float(str(item).replace(",", "").replace("%", "").strip())
                    except (TypeError, ValueError):
                        pass
                found = walk(item)
                if found is not None:
                    return found
            return None

        return walk(row)

    @staticmethod
    def _find_value(row: dict[str, Any], names: tuple[str, ...]) -> Any:
        wanted = {name.lower().replace("_", "") for name in names}

        def walk(value: Any) -> Any:
            if not isinstance(value, dict):
                return None
            for key, item in value.items():
                if str(key).lower().replace("_", "") in wanted and item not in (None, ""):
                    return item
                found = walk(item)
                if found not in (None, ""):
                    return found
            return None

        return walk(row)

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
        return self._rows(data)

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
        return self._rows(data)

    def shareholding(self, symbol: str) -> dict[str, Any]:
        """Return the latest NSE shareholding-pattern snapshot."""
        data = self._get_json(
            self.SHAREHOLDING_URL,
            {"index": "equities", "symbol": symbol.upper().strip()},
        )
        rows = self._rows(data)
        if not rows:
            return {
                "symbol": symbol.upper().strip(),
                "available": False,
                "rows": [],
                "data_gap": "NSE shareholding pattern unavailable",
            }

        def date_key(row: dict[str, Any]) -> str:
            return str(
                row.get("asOnDate")
                or row.get("as_on_date")
                or row.get("asOn")
                or row.get("date")
                or ""
            )

        ordered = sorted(rows, key=date_key, reverse=True)
        latest = ordered[0]
        prior = ordered[1] if len(ordered) > 1 else None

        promoter = self._find_number(
            latest,
            ("promoterAndPromoterGroup", "promoterGroup", "promoterHolding", "promoter", "promoterPct", "promoterPercent"),
        )
        public = self._find_number(
            latest,
            ("public", "publicHolding", "publicPct", "publicPercent"),
        )
        pledge = self._find_number(
            latest,
            ("promoterPledge", "promoterPledgePct", "pledged", "pledgedSharesPct", "encumbered", "encumberedPct"),
        )
        prior_promoter = self._find_number(
            prior or {},
            ("promoterAndPromoterGroup", "promoterGroup", "promoterHolding", "promoter", "promoterPct", "promoterPercent"),
        )
        promoter_change = promoter - prior_promoter if promoter is not None and prior_promoter is not None else None

        return {
            "symbol": symbol.upper().strip(),
            "available": True,
            "as_on_date": date_key(latest),
            "submission_date": self._find_value(latest, ("submissionDate", "submission_date", "filedDate")),
            "broadcast_date": self._find_value(latest, ("broadcastDate", "broadcast_date")),
            "xbrl_url": self._find_value(latest, ("xbrl", "xbrlUrl", "xbrlFileLink", "xbrlFile")),
            "promoter_holding_pct": promoter,
            "public_holding_pct": public,
            "promoter_pledge_pct": pledge,
            "promoter_change_pct": promoter_change,
            "rows": ordered,
        }

    def _data_gap(self, symbol: str, error: Exception) -> dict[str, Any]:
        return {
            "symbol": symbol.upper().strip(),
            "announcements": [],
            "pit": [],
            "pit_risk_rows": [],
            "shareholding": {
                "symbol": symbol.upper().strip(),
                "available": False,
                "rows": [],
                "data_gap": f"NSE access unavailable: {type(error).__name__}",
            },
            "promoter_holding_pct": None,
            "promoter_pledge_pct": None,
            "promoter_change_pct": None,
            "source": "NSE corporate-announcements + NSE PIT + NSE shareholding pattern",
            "data_gap": f"NSE corporate filing access unavailable: {type(error).__name__}: {error}",
            "available": False,
        }

    def risk_inputs(self, symbol: str, days: int = 180) -> dict[str, Any]:
        """Collect mechanical filing signals for corporate-risk assessment."""
        try:
            announcements = self.announcements(symbol, days=days)
            pit_rows = self.pit(symbol, days=max(days, 365))
            shareholding = self.shareholding(symbol)
        except (RequestException, ValueError) as exc:
            return self._data_gap(symbol, exc)

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
            "shareholding": shareholding,
            "promoter_holding_pct": shareholding.get("promoter_holding_pct"),
            "promoter_pledge_pct": shareholding.get("promoter_pledge_pct"),
            "promoter_change_pct": shareholding.get("promoter_change_pct"),
            "source": "NSE corporate-announcements + NSE PIT + NSE shareholding pattern",
            "available": True,
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
