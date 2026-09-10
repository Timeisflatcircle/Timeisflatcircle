from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class SmallMicrocapConfig:
    """Conservative defaults for Indian small/micro-cap idea generation.

    Market-cap and liquidity limits are screening aids, not exchange classifications.
    They should be configurable as the investable universe changes.
    """

    smallcap_max_cr: float = 50000.0
    microcap_max_cr: float = 5000.0
    nano_cap_min_cr: float = 500.0
    min_avg_daily_value_cr: float = 0.10
    min_price: float = 10.0
    max_promoter_pledge_pct: float = 5.0
    max_debt_to_equity: float = 1.5
    min_roce_pct: float = 10.0
    min_revenue_cagr_pct: float = 5.0
    min_pat_cagr_pct: float = 5.0
    min_cfo_pat: float = 0.60


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
    """Return a deterministic 0-100 risk score; higher means safer."""
    cfg = config or SmallMicrocapConfig()
    score = 0
    flags: List[str] = []

    liquidity = float(row.get("avg_daily_value_cr", 0) or 0)
    pledge = float(row.get("promoter_pledge_pct", 0) or 0)
    debt = float(row.get("debt_to_equity", 0) or 0)
    audit_clean = bool(row.get("audit_clean", True))
    auditor_change = bool(row.get("auditor_change", False))
    related_party_high = bool(row.get("related_party_high", False))
    preferential_allotment = bool(row.get("preferential_allotment", False))
    cfo_pat = float(row.get("cfo_pat", 0) or 0)

    score += 20 if liquidity >= 1.0 else 12 if liquidity >= cfg.min_avg_daily_value_cr else 0
    score += 20 if pledge <= 0 else 12 if pledge <= cfg.max_promoter_pledge_pct else 0
    score += 20 if debt <= 0.5 else 12 if debt <= cfg.max_debt_to_equity else 0
    score += 20 if cfo_pat >= 1.0 else 12 if cfo_pat >= cfg.min_cfo_pat else 0
    score += 20 if audit_clean and not auditor_change and not related_party_high else 0

    if liquidity < cfg.min_avg_daily_value_cr:
        flags.append("LOW_LIQUIDITY")
    if pledge > cfg.max_promoter_pledge_pct:
        flags.append("HIGH_PROMOTER_PLEDGE")
    if auditor_change:
        flags.append("AUDITOR_CHANGE")
    if related_party_high:
        flags.append("HIGH_RELATED_PARTY_RISK")
    if preferential_allotment:
        flags.append("PREFERENTIAL_ALLOTMENT")
    if debt > cfg.max_debt_to_equity:
        flags.append("HIGH_LEVERAGE")
    if cfo_pat < cfg.min_cfo_pat:
        flags.append("WEAK_CASH_CONVERSION")
    if not audit_clean:
        flags.append("AUDIT_QUALIFICATION")

    hard_fail = any(flag in flags for flag in ("AUDIT_QUALIFICATION", "HIGH_PROMOTER_PLEDGE", "HIGH_RELATED_PARTY_RISK"))
    risk_band = "A" if score >= 80 and not hard_fail else "B" if score >= 65 and not hard_fail else "C" if score >= 50 else "D"
    return {"risk_score_100": score, "risk_band": risk_band, "flags": flags, "hard_fail": hard_fail}


def screen_small_microcap(row: Dict[str, Any], config: SmallMicrocapConfig | None = None) -> Dict[str, Any]:
    cfg = config or SmallMicrocapConfig()
    market_cap = float(row.get("market_cap_cr", 0) or 0)
    category = classify_market_cap(market_cap, cfg)
    risk = calculate_microcap_risk_score(row, cfg)

    failures: List[str] = []
    if category == "NANO / EXCLUDE" or category == "LARGER THAN TARGET":
        failures.append(category)
    if float(row.get("avg_daily_value_cr", 0) or 0) < cfg.min_avg_daily_value_cr:
        failures.append("LIQUIDITY_BELOW_MINIMUM")
    if float(row.get("price", 0) or 0) < cfg.min_price:
        failures.append("PRICE_BELOW_MINIMUM")
    if float(row.get("promoter_pledge_pct", 0) or 0) > cfg.max_promoter_pledge_pct:
        failures.append("PROMOTER_PLEDGE_TOO_HIGH")
    if float(row.get("roce_pct", 0) or 0) < cfg.min_roce_pct:
        failures.append("LOW_ROCE")
    if float(row.get("revenue_cagr_pct", 0) or 0) < cfg.min_revenue_cagr_pct:
        failures.append("LOW_REVENUE_GROWTH")
    if float(row.get("pat_cagr_pct", 0) or 0) < cfg.min_pat_cagr_pct:
        failures.append("LOW_PAT_GROWTH")
    if not bool(row.get("audit_clean", True)):
        failures.append("AUDIT_QUALIFICATION")

    eligible = not failures and not risk["hard_fail"]
    return {
        "eligible": eligible,
        "market_cap_category": category,
        "risk": risk,
        "failures": failures,
    }


def rank_candidates(rows: List[Dict[str, Any]], config: SmallMicrocapConfig | None = None) -> List[Dict[str, Any]]:
    """Screen and rank candidates without any LLM involvement."""
    cfg = config or SmallMicrocapConfig()
    results = []
    for row in rows:
        result = screen_small_microcap(row, cfg)
        results.append({**row, **result})
    return sorted(
        results,
        key=lambda x: (
            x["eligible"],
            x["risk"]["risk_score_100"],
            float(x.get("pat_cagr_pct", 0) or 0),
            float(x.get("roce_pct", 0) or 0),
        ),
        reverse=True,
    )
