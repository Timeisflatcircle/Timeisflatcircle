from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class SmallMicrocapConfig:
    """Conservative screening bands for Indian small/micro-cap idea generation."""
    smallcap_max_cr: float = 50000.0
    microcap_max_cr: float = 5000.0
    nano_cap_min_cr: float = 500.0
    min_daily_traded_value_cr: float = 0.10
    min_price: float = 10.0
    max_promoter_pledge_pct: float = 5.0
    max_debt_to_equity: float = 1.5
    min_roce_pct: float = 10.0
    min_revenue_cagr_pct: float = 5.0
    min_pat_cagr_pct: float = 5.0
    min_cfo_pat: float = 0.60


def _number(row: Dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_market_cap(market_cap_cr: float, config: SmallMicrocapConfig | None = None) -> str:
    cfg = config or SmallMicrocapConfig()
    if market_cap_cr < cfg.nano_cap_min_cr:
        return "NANO / EXCLUDE"
    if market_cap_cr <= cfg.microcap_max_cr:
        return "MICROCAP"
    if market_cap_cr <= cfg.smallcap_max_cr:
        return "SMALLCAP"
    return "LARGER THAN TARGET"


def calculate_microcap_risk_score(row: Dict[str, Any], config: SmallMicrocapConfig | None = None) -> Dict[str, Any]:
    """Deterministic 0-100 safety score; unknown inputs get zero points."""
    cfg = config or SmallMicrocapConfig()
    score = 0
    flags: List[str] = []

    liquidity = _number(row, "avg_daily_value_cr")
    if liquidity is None:
        liquidity = _number(row, "daily_traded_value_cr")
    pledge = _number(row, "promoter_pledge_pct")
    debt = _number(row, "debt_to_equity")
    cfo_pat = _number(row, "cfo_pat")
    audit_clean = row.get("audit_clean")
    auditor_change = row.get("auditor_change")
    related_party_high = row.get("related_party_high")
    preferential_allotment = row.get("preferential_allotment")

    if liquidity is None:
        flags.append("DATA_GAP_LIQUIDITY")
    else:
        score += 20 if liquidity >= 1.0 else 12 if liquidity >= cfg.min_daily_traded_value_cr else 0
        if liquidity < cfg.min_daily_traded_value_cr:
            flags.append("LOW_LIQUIDITY")

    if pledge is None:
        flags.append("DATA_GAP_PROMOTER_PLEDGE")
    else:
        score += 20 if pledge <= 0 else 12 if pledge <= cfg.max_promoter_pledge_pct else 0
        if pledge > cfg.max_promoter_pledge_pct:
            flags.append("HIGH_PROMOTER_PLEDGE")

    if debt is None:
        flags.append("DATA_GAP_LEVERAGE")
    else:
        score += 20 if debt <= 0.5 else 12 if debt <= cfg.max_debt_to_equity else 0
        if debt > cfg.max_debt_to_equity:
            flags.append("HIGH_LEVERAGE")

    if cfo_pat is None:
        flags.append("DATA_GAP_CASH_CONVERSION")
    else:
        score += 20 if cfo_pat >= 1.0 else 12 if cfo_pat >= cfg.min_cfo_pat else 0
        if cfo_pat < cfg.min_cfo_pat:
            flags.append("WEAK_CASH_CONVERSION")

    if audit_clean is None or auditor_change is None or related_party_high is None:
        flags.append("DATA_GAP_GOVERNANCE")
    elif audit_clean and not auditor_change and not related_party_high:
        score += 20

    if auditor_change is True:
        flags.append("AUDITOR_CHANGE")
    if related_party_high is True:
        flags.append("HIGH_RELATED_PARTY_RISK")
    if preferential_allotment is True:
        flags.append("PREFERENTIAL_ALLOTMENT")
    if audit_clean is False:
        flags.append("AUDIT_QUALIFICATION")

    hard_fail = any(flag in flags for flag in ("AUDIT_QUALIFICATION", "HIGH_PROMOTER_PLEDGE", "HIGH_RELATED_PARTY_RISK"))
    # Hard failures always map to the worst risk band, regardless of the raw score.
    risk_band = "D" if hard_fail else "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D"
    return {"risk_score_100": score, "risk_band": risk_band, "flags": flags, "hard_fail": hard_fail}


def screen_small_microcap(row: Dict[str, Any], config: SmallMicrocapConfig | None = None) -> Dict[str, Any]:
    cfg = config or SmallMicrocapConfig()
    market_cap = _number(row, "market_cap_cr")
    failures: List[str] = []
    if market_cap is None:
        category = "UNKNOWN"
        failures.append("DATA_GAP_MARKET_CAP")
    else:
        category = classify_market_cap(market_cap, cfg)
        if category in ("NANO / EXCLUDE", "LARGER THAN TARGET"):
            failures.append(category)

    price = _number(row, "price")
    liquidity = _number(row, "avg_daily_value_cr")
    if liquidity is None:
        liquidity = _number(row, "daily_traded_value_cr")
    pledge = _number(row, "promoter_pledge_pct")
    roce = _number(row, "roce_pct")
    revenue_cagr = _number(row, "revenue_cagr_pct")
    pat_cagr = _number(row, "pat_cagr_pct")

    if liquidity is None:
        failures.append("DATA_GAP_LIQUIDITY")
    elif liquidity < cfg.min_daily_traded_value_cr:
        failures.append("LIQUIDITY_BELOW_MINIMUM")
    if price is None:
        failures.append("DATA_GAP_PRICE")
    elif price < cfg.min_price:
        failures.append("PRICE_BELOW_MINIMUM")
    if pledge is None:
        failures.append("DATA_GAP_PROMOTER_PLEDGE")
    elif pledge > cfg.max_promoter_pledge_pct:
        failures.append("PROMOTER_PLEDGE_TOO_HIGH")
    if roce is None:
        failures.append("DATA_GAP_ROCE")
    elif roce < cfg.min_roce_pct:
        failures.append("LOW_ROCE")
    if revenue_cagr is None:
        failures.append("DATA_GAP_REVENUE_GROWTH")
    elif revenue_cagr < cfg.min_revenue_cagr_pct:
        failures.append("LOW_REVENUE_GROWTH")
    if pat_cagr is None:
        failures.append("DATA_GAP_PAT_GROWTH")
    elif pat_cagr < cfg.min_pat_cagr_pct:
        failures.append("LOW_PAT_GROWTH")

    audit_clean = row.get("audit_clean")
    if audit_clean is None:
        failures.append("DATA_GAP_AUDIT")
    elif audit_clean is False:
        failures.append("AUDIT_QUALIFICATION")

    risk = calculate_microcap_risk_score(row, cfg)
    eligible = not failures and not risk["hard_fail"]
    return {"eligible": eligible, "market_cap_category": category, "risk": risk, "failures": failures}


def rank_candidates(rows: List[Dict[str, Any]], config: SmallMicrocapConfig | None = None) -> List[Dict[str, Any]]:
    cfg = config or SmallMicrocapConfig()
    results = []
    for row in rows:
        result = screen_small_microcap(row, cfg)
        results.append({**row, **result})
    return sorted(results, key=lambda x: (x["eligible"], x["risk"]["risk_score_100"], float(x.get("pat_cagr_pct", 0) or 0), float(x.get("roce_pct", 0) or 0)), reverse=True)
