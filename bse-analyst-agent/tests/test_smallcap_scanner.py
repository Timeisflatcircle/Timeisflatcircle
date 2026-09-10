from src.smallcap_scanner import (
    SmallMicrocapConfig,
    calculate_microcap_risk_score,
    classify_market_cap,
    rank_candidates,
    screen_small_microcap,
)


def good_row():
    return {
        "symbol": "GOOD",
        "market_cap_cr": 3200,
        "price": 150,
        "avg_daily_value_cr": 2.0,
        "promoter_pledge_pct": 0,
        "debt_to_equity": 0.25,
        "cfo_pat": 1.05,
        "roce_pct": 18,
        "revenue_cagr_pct": 14,
        "pat_cagr_pct": 18,
        "audit_clean": True,
        "auditor_change": False,
        "related_party_high": False,
    }


def test_market_cap_classification():
    cfg = SmallMicrocapConfig()
    assert classify_market_cap(3000, cfg) == "MICROCAP"
    assert classify_market_cap(20000, cfg) == "SMALLCAP"
    assert classify_market_cap(300, cfg) == "NANO / EXCLUDE"


def test_good_candidate_is_eligible():
    result = screen_small_microcap(good_row())
    assert result["eligible"] is True
    assert result["risk"]["risk_band"] == "A"


def test_high_pledge_is_hard_fail():
    row = good_row()
    row["promoter_pledge_pct"] = 12
    result = screen_small_microcap(row)
    assert result["eligible"] is False
    assert result["risk"]["hard_fail"] is True
    assert "PROMOTER_PLEDGE_TOO_HIGH" in result["failures"]


def test_low_liquidity_is_rejected():
    row = good_row()
    row["avg_daily_value_cr"] = 0.03
    result = screen_small_microcap(row)
    assert result["eligible"] is False
    assert "LIQUIDITY_BELOW_MINIMUM" in result["failures"]


def test_bad_audit_is_rejected():
    row = good_row()
    row["audit_clean"] = False
    result = screen_small_microcap(row)
    assert result["eligible"] is False
    assert result["risk"]["risk_band"] == "D"


def test_ranking_prefers_eligible_candidate():
    bad = good_row()
    bad["symbol"] = "BAD"
    bad["roce_pct"] = 4
    ranked = rank_candidates([bad, good_row()])
    assert ranked[0]["symbol"] == "GOOD"
