from src.candidate_ranker import pre_deep_score, rank_for_deep_analysis


def row(symbol, market_cap, price, liquidity):
    return {
        "symbol": symbol,
        "company_name": symbol,
        "market_cap_cr": market_cap,
        "price": price,
        "avg_daily_value_cr": liquidity,
        "source": "test",
    }


def test_score_is_bounded():
    score = pre_deep_score(row("TEST", 2500, 100, 10))
    assert 0 <= score <= 100


def test_ranking_prefers_liquid_candidate():
    rows = [row("LOW", 2500, 100, 0.2), row("HIGH", 2500, 100, 15)]
    ranked = rank_for_deep_analysis(rows, deep_limit=2)
    assert ranked[0]["symbol"] == "HIGH"
    assert "pre_deep_score" in ranked[0]


def test_deep_limit_is_respected():
    rows = [row(str(i), 2500, 100, 5) for i in range(5)]
    assert len(rank_for_deep_analysis(rows, deep_limit=3)) == 3
    assert rank_for_deep_analysis(rows, deep_limit=0) == []
