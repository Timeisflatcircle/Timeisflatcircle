from types import SimpleNamespace

import src.deep_scanner as deep_scanner


def test_complete_analysis_requires_final_payload():
    result = {
        "status": "ANALYZED",
        "verdict": "WATCHLIST",
        "quality_score": 72,
        "ai_conviction": 7,
        "thesis": "Solid business, valuation needs patience.",
    }
    assert deep_scanner._is_complete_analysis(result)


def test_incomplete_analysis_is_not_counted():
    result = {
        "status": "ANALYZED",
        "verdict": "WATCHLIST",
        "quality_score": 72,
        "ai_conviction": 7,
        "thesis": "",
    }
    assert not deep_scanner._is_complete_analysis(result)


def test_corporate_reject_is_explicit(monkeypatch):
    class FakeFilings:
        def cached_risk_inputs(self, symbol):
            return {
                "announcements": [],
                "pit_risk_rows": [],
                "shareholding": {},
                "promoter_holding_pct": 55,
                "promoter_pledge_pct": 25,
                "promoter_change_pct": 0,
                "source": "test",
            }

    result = deep_scanner.analyze_candidate(
        {"symbol": "TEST", "price": "100", "market_cap_cr": "1000"},
        filings_client=FakeFilings(),
        live_filings=True,
    )
    assert result["status"] == "CORPORATE_RISK_REJECT"
    assert result["stage"] == "CORPORATE_RISK"
    assert result["verdict"] == "AVOID"
    assert "pledge" in result["corporate_risk_flags"].lower()


def test_run_deep_scan_reports_failures_and_checkpoints(tmp_path, monkeypatch, capsys):
    input_csv = tmp_path / "input.csv"
    input_csv.write_text(
        "symbol,price,market_cap_cr\nGOOD,100,1000\nBAD,100,1000\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(deep_scanner, "AnalysisOrchestrator", lambda: object())

    def fake_analyze(row, orchestrator, filings, live_filings):
        if row["symbol"] == "GOOD":
            return {
                **row,
                "status": "ANALYZED",
                "stage": "COMPLETE",
                "verdict": "WATCHLIST",
                "quality_score": 70,
                "ai_conviction": 7,
                "thesis": "Test thesis",
            }
        return {
            **row,
            "status": "ERROR",
            "stage": "EXCEPTION",
            "error": "RuntimeError: test failure",
        }

    monkeypatch.setattr(deep_scanner, "analyze_candidate", fake_analyze)

    selected = deep_scanner.run_deep_scan(
        input_csv=str(input_csv),
        top=10,
        deep_limit=2,
        output_dir=str(tmp_path),
        live_filings=False,
    )

    output = capsys.readouterr().out
    assert len(selected) == 1
    assert selected[0]["symbol"] == "GOOD"
    assert "ANALYZED=1" in output
    assert "ERROR=1" in output
    assert "test failure" in output
    checkpoint = tmp_path / "small_microcap_deep_analysis.csv"
    assert checkpoint.exists()
    assert "GOOD" in checkpoint.read_text(encoding="utf-8")
    assert "BAD" in checkpoint.read_text(encoding="utf-8")
