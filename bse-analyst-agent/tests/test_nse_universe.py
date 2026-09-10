from src.nse_universe import NSEUniverse


class FakeResponse:
    def __init__(self, payload=None, text="", status_code=200):
        self._payload = payload
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_yahoo_chart_quote_parses_price_and_volume():
    universe = NSEUniverse()
    universe.session.get = lambda *args, **kwargs: FakeResponse({
        "chart": {
            "result": [{
                "meta": {
                    "regularMarketPrice": 1274.0,
                    "regularMarketVolume": 9290437,
                    "longName": "Reliance Industries Limited",
                },
                "indicators": {"quote": [{"volume": [9290437]}]},
            }]
        }
    })

    row = universe._yahoo_quote("RELIANCE")

    assert row["price"] == 1274.0
    assert row["volume"] == 9290437.0
    assert row["company_name"] == "Reliance Industries Limited"
    assert row["market_cap_cr"] is None


def test_yahoo_market_caps_converts_inr_to_crore(monkeypatch):
    universe = NSEUniverse()
    universe.yahoo_crumb = "crumb"

    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse({
            "quoteResponse": {
                "result": [
                    {"symbol": "RELIANCE.NS", "marketCap": 17200000000000},
                    {"symbol": "TCS.NS", "marketCap": 15000000000000},
                ]
            }
        })

    monkeypatch.setattr(universe.session, "get", fake_get)
    result = universe._yahoo_market_caps(["RELIANCE", "TCS"])

    assert result["RELIANCE"] == 1720000.0
    assert result["TCS"] == 1500000.0
    assert calls[0][1]["params"]["crumb"] == "crumb"


def test_quote_fallback_enriches_market_cap(monkeypatch):
    universe = NSEUniverse()
    monkeypatch.setattr(universe, "_init_session", lambda: (_ for _ in ()).throw(RuntimeError("NSE blocked")))
    monkeypatch.setattr(universe, "_yahoo_quote", lambda symbol: {
        "symbol": symbol,
        "company_name": "Reliance Industries Limited",
        "price": 1274.0,
        "market_cap_cr": None,
        "avg_daily_value_cr": 1183.6,
        "volume": 9290437.0,
        "source": "Yahoo Finance chart fallback",
    })
    monkeypatch.setattr(universe, "_yahoo_market_caps", lambda symbols: {"RELIANCE": 1720000.0})

    row = universe.quote("RELIANCE")

    assert row["market_cap_cr"] == 1720000.0
    assert row["source"] == "Yahoo Finance chart + quote fallback"
