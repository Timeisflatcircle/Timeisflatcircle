from src.market_cap_cache import MarketCapCache


def test_refresh_uses_batched_market_caps(monkeypatch, tmp_path):
    client = MarketCapCache(cache_path=str(tmp_path / "market_caps.json"), batch_size=2, request_delay=0)
    calls = []

    def fake_batch(symbols):
        calls.append(list(symbols))
        return {symbol: {"market_cap_cr": float(i + 1), "as_of": "2099-01-01T00:00:00", "source": "test"} for i, symbol in enumerate(symbols)}

    monkeypatch.setattr(client, "_fetch_batch", fake_batch)
    result = client.refresh(["RELIANCE", "INFY", "ITC"])

    assert calls == [["INFY", "ITC"], ["RELIANCE"]]
    assert result["RELIANCE"]["market_cap_cr"] == 1.0
    assert (tmp_path / "market_caps.json").exists()


def test_get_returns_fresh_cached_value(tmp_path):
    client = MarketCapCache(cache_path=str(tmp_path / "market_caps.json"), ttl_hours=24)
    client._save({"RELIANCE": {"market_cap_cr": 1724036.99, "as_of": "2099-01-01T00:00:00", "source": "test"}})
    assert client.get("RELIANCE") == 1724036.99


def test_ensure_fresh_does_not_refresh_complete_cache(monkeypatch, tmp_path):
    client = MarketCapCache(cache_path=str(tmp_path / "market_caps.json"), ttl_hours=24)
    client._save({
        "RELIANCE": {"market_cap_cr": 1724036.99, "as_of": "2099-01-01T00:00:00", "source": "test"},
        "INFY": {"market_cap_cr": 500000.0, "as_of": "2099-01-01T00:00:00", "source": "test"},
    })
    called = []
    monkeypatch.setattr(client, "refresh", lambda symbols: called.append(symbols) or client._load())

    result = client.ensure_fresh(["RELIANCE", "INFY"])

    assert called == []
    assert result["RELIANCE"]["market_cap_cr"] == 1724036.99


def test_ensure_fresh_refreshes_when_symbol_is_missing(monkeypatch, tmp_path):
    client = MarketCapCache(cache_path=str(tmp_path / "market_caps.json"), ttl_hours=24)
    client._save({"RELIANCE": {"market_cap_cr": 1724036.99, "as_of": "2099-01-01T00:00:00", "source": "test"}})
    called = []
    monkeypatch.setattr(client, "refresh", lambda symbols: called.append(symbols) or {"RELIANCE": {"market_cap_cr": 1724036.99, "as_of": "2099-01-01T00:00:00", "source": "test"}, "INFY": {"market_cap_cr": 500000.0, "as_of": "2099-01-01T00:00:00", "source": "test"}})

    result = client.ensure_fresh(["RELIANCE", "INFY"])

    assert called == [["INFY", "RELIANCE"]]
    assert result["INFY"]["market_cap_cr"] == 500000.0


def test_missing_market_cap_returns_none(tmp_path):
    client = MarketCapCache(cache_path=str(tmp_path / "market_caps.json"))
    assert client.get("UNKNOWN") is None
