from typing import Any, Dict, List

DEFAULT_WEIGHTS = {"liquidity": 0.35, "market_cap": 0.25, "price": 0.10, "data_completeness": 0.30}


def _number(row: Dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def pre_deep_score(row: Dict[str, Any]) -> float:
    """Prioritize Stage-1 candidates; this is not an investment recommendation."""
    liquidity = _number(row, "avg_daily_value_cr")
    market_cap = _number(row, "market_cap_cr")
    price = _number(row, "price")
    liquidity_score = 0.0 if liquidity is None else _bounded(liquidity, 0.10, 25.0)
    if market_cap is None:
        market_cap_score = 0.0
    elif market_cap <= 500:
        market_cap_score = 0.20
    elif market_cap <= 5000:
        market_cap_score = 1.0 - abs(market_cap - 2500) / 2500
    else:
        market_cap_score = max(0.0, 1.0 - (market_cap - 5000) / 45000)
    price_score = 0.0 if price is None or price < 10 else min(1.0, price / 250.0)
    tracked = ("symbol", "company_name", "market_cap_cr", "price", "avg_daily_value_cr", "source")
    completeness_score = sum(row.get(key) not in (None, "") for key in tracked) / len(tracked)
    return round(100 * (0.35 * liquidity_score + 0.25 * market_cap_score + 0.10 * price_score + 0.30 * completeness_score), 2)


def rank_for_deep_analysis(rows: List[Dict[str, Any]], deep_limit: int = 20) -> List[Dict[str, Any]]:
    """Return Stage-1 rows prioritized for expensive Stage-2 analysis."""
    if deep_limit < 1:
        return []
    ranked = []
    for row in rows:
        scored = dict(row)
        scored["pre_deep_score"] = pre_deep_score(row)
        ranked.append(scored)
    ranked.sort(key=lambda row: (float(row.get("pre_deep_score", 0) or 0), float(row.get("avg_daily_value_cr", 0) or 0)), reverse=True)
    return ranked[:deep_limit]
