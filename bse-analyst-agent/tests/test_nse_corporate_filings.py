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


def test_shareholding_extracts_latest_promoter_and_change(monkeypatch, tmp_path):
    client = NSECorporateFilings(cache_dir=str(tmp_path), request_delay=0)
    monkeypatch.setattr(
        client,
        "_get_json",
        lambda *args, **kwargs: {
            "data": [
                {"asOnDate": "31-MAR-2026", "promoterAndPromoterGroup": "41.5", "public": "58.5", "xbrl": "https://example/xbrl.xml"},
                {"asOnDate": "31-DEC-2025", "promoterAndPromoterGroup": "40.0", "public": "60.0"},
            ]
        },
    )
    result = client.shareholding("ABC")
    assert result["available"] is True
    assert result["promoter_holding_pct"] == 41.5
    assert result["promoter_change_pct"] == 1.5
    assert result["xbrl_url"].endswith("xbrl.xml")


def test_shareholding_handles_nse_summary_public_val_and_chronological_order(monkeypatch, tmp_path):
    client = NSECorporateFilings(cache_dir=str(tmp_path), request_delay=0)
    monkeypatch.setattr(
        client,
        "_get_json",
        lambda *args, **kwargs: {
            "data": [
                {"asOnDate": "18-DEC-2021", "public_val": "49.38", "submissionDate": "18-DEC-2021"},
                {"asOnDate": "30-JUN-2026", "public_val": "49.52", "submissionDate": "16-JUL-2026"},
                {"asOnDate": "31-MAR-2026", "public_val": "50.00", "submissionDate": "21-APR-2026"},
            ]
        },
    )
    result = client.shareholding("RELIANCE")
    assert result["as_on_date"] == "30-JUN-2026"
    assert result["promoter_holding_pct"] == 50.48
    assert result["public_holding_pct"] == 49.52
    assert result["promoter_change_pct"] == 0.48


def test_risk_inputs_include_shareholding(monkeypatch, tmp_path):
    client = NSECorporateFilings(cache_dir=str(tmp_path), request_delay=0)
    monkeypatch.setattr(client, "announcements", lambda symbol, days: [])
    monkeypatch.setattr(client, "pit", lambda symbol, days: [])
    monkeypatch.setattr(
        client,
        "shareholding",
        lambda symbol: {
            "available": True,
            "promoter_holding_pct": 52.0,
            "promoter_pledge_pct": 2.0,
            "promoter_change_pct": -1.0,
            "as_on_date": "30-JUN-2026",
        },
    )
    result = client.risk_inputs("ABC")
    assert result["promoter_holding_pct"] == 52.0
    assert result["promoter_pledge_pct"] == 2.0
    assert result["promoter_change_pct"] == -1.0
    assert "shareholding pattern" in result["source"]


def test_cached_risk_inputs_writes_cache(monkeypatch, tmp_path):
    client = NSECorporateFilings(cache_dir=str(tmp_path), request_delay=0)
    monkeypatch.setattr(client, "risk_inputs", lambda symbol, days: {"symbol": symbol, "announcements": [], "pit": [], "pit_risk_rows": []})
    result = client.cached_risk_inputs("ABC")
    assert result["symbol"] == "ABC"
    assert (tmp_path / "ABC_filings.json").exists()
