from src.nse_corporate_filings import NSECorporateFilings


def test_announcements_normalize_dict_payload(monkeypatch, tmp_path):
    client = NSECorporateFilings(cache_dir=str(tmp_path), request_delay=0)
    monkeypatch.setattr(client, "_get_json", lambda *args, **kwargs: {"data": [{"desc": "Fund Raising", "attchmntText": "Preferential allotment", "an_dt": "01-Sep-2026"}]})
    rows = client.announcements("ABC", days=30)
    assert rows[0]["desc"] == "Fund Raising"


def test_pit_normalize_dict_payload(monkeypatch, tmp_path):
    client = NSECorporateFilings(cache_dir=str(tmp_path), request_delay=0)
    monkeypatch.setattr(client, "_get_json", lambda *args, **kwargs: {"data": [{"categoryName": "Promoters", "buySell": "SELL"}]})
    rows = client.pit("ABC", days=30)
    assert rows[0]["categoryName"] == "Promoters"


def test_cached_risk_inputs_writes_cache(monkeypatch, tmp_path):
    client = NSECorporateFilings(cache_dir=str(tmp_path), request_delay=0)
    monkeypatch.setattr(client, "risk_inputs", lambda symbol, days: {"symbol": symbol, "announcements": [], "pit": [], "pit_risk_rows": []})
    result = client.cached_risk_inputs("ABC")
    assert result["symbol"] == "ABC"
    assert (tmp_path / "ABC_filings.json").exists()
