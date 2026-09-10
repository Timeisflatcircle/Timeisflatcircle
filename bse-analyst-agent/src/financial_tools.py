from typing import Dict, Any, List
from pydantic import BaseModel, Field


class AnnualFinancials(BaseModel):
    fiscal_year: str = Field(description="Fiscal year label, e.g. FY2026")
    revenue: float = Field(description="Revenue from operations, INR Cr")
    ebit: float = Field(description="Operating profit / EBIT, INR Cr")
    pat: float = Field(description="Profit after tax attributable to shareholders, INR Cr")
    total_debt: float = Field(description="Total debt including lease liabilities, INR Cr")
    total_equity: float = Field(description="Shareholders' equity / net worth, INR Cr")
    cash_equivalents: float = Field(description="Cash, cash equivalents and current investments, INR Cr")
    cfo: float = Field(description="Cash flow from operating activities, INR Cr")
    interest_expense: float = Field(description="Finance costs / interest expense, INR Cr")
    capex: float = Field(default=0.0, description="Capital expenditure / purchase of PPE and intangibles, INR Cr; positive amount")


class CompanyFinancialHistory(BaseModel):
    years: List[AnnualFinancials] = Field(min_length=3, max_length=5, description="Oldest fiscal year first, latest fiscal year last")


CompanyFinancialInputs = AnnualFinancials


def _growth(new: float, old: float) -> float:
    return ((new - old) / old * 100.0) if old else 0.0


def calculate_fundamental_ratios(data: CompanyFinancialHistory) -> Dict[str, Any]:
    years = data.years
    latest, prior = years[-1], years[-2]

    capital_employed = latest.total_equity + latest.total_debt - latest.cash_equivalents
    roce = latest.ebit / capital_employed * 100 if capital_employed > 0 else 0.0
    roe = latest.pat / latest.total_equity * 100 if latest.total_equity > 0 else 0.0
    net_debt = latest.total_debt - latest.cash_equivalents
    de_ratio = latest.total_debt / latest.total_equity if latest.total_equity else 0.0
    interest_coverage = latest.ebit / latest.interest_expense if latest.interest_expense > 0 else 999.0
    cfo_to_pat = latest.cfo / latest.pat if latest.pat > 0 else 0.0
    rev_growth_yoy = _growth(latest.revenue, prior.revenue)
    pat_growth_yoy = _growth(latest.pat, prior.pat)

    first, n = years[0], len(years) - 1
    revenue_cagr = ((latest.revenue / first.revenue) ** (1 / n) - 1) * 100 if first.revenue > 0 and latest.revenue > 0 else 0.0
    pat_cagr = ((latest.pat / first.pat) ** (1 / n) - 1) * 100 if first.pat > 0 and latest.pat > 0 else 0.0

    margins = [y.pat / y.revenue * 100 for y in years if y.revenue > 0]
    latest_margin = margins[-1] if margins else 0.0
    avg_margin = sum(margins) / len(margins) if margins else 0.0
    margin_stability = max(margins) - min(margins) if margins else 0.0
    positive_cfo_years = sum(1 for y in years if y.cfo > 0)
    conversion = [y.cfo / y.pat for y in years if y.pat > 0]
    avg_cash_conversion = sum(conversion) / len(conversion) if conversion else 0.0

    hurdles = {
        "roce_above_15": roce >= 15.0,
        "clean_debt": de_ratio <= 1.0 or net_debt <= 0,
        "cash_conversion_sound": cfo_to_pat >= 0.70,
        "healthy_coverage": interest_coverage >= 3.5,
        "five_year_cfo_positive": positive_cfo_years >= max(3, len(years) - 1),
    }

    return {
        "years_analyzed": len(years),
        "latest_fiscal_year": latest.fiscal_year,
        "ROCE (%)": round(roce, 2),
        "ROE (%)": round(roe, 2),
        "Revenue YoY Growth (%)": round(rev_growth_yoy, 2),
        "PAT YoY Growth (%)": round(pat_growth_yoy, 2),
        "Revenue CAGR (%)": round(revenue_cagr, 2),
        "PAT CAGR (%)": round(pat_cagr, 2),
        "Latest PAT Margin (%)": round(latest_margin, 2),
        "Average PAT Margin (%)": round(avg_margin, 2),
        "PAT Margin Range (pp)": round(margin_stability, 2),
        "Debt to Equity": round(de_ratio, 2),
        "Net Debt (Cr)": round(net_debt, 2),
        "Interest Coverage Ratio": round(interest_coverage, 2),
        "CFO / PAT Quality Ratio": round(cfo_to_pat, 2),
        "Average CFO / PAT (5Y)": round(avg_cash_conversion, 2),
        "Positive CFO Years": f"{positive_cfo_years}/{len(years)}",
        "hurdles_passed": hurdles,
    }


def calculate_quality_score(ratios: Dict[str, Any], governance_clean: bool = True) -> Dict[str, Any]:
    """Deterministic 100-point score. LLM explains the result; Python owns the score."""
    components = {
        "capital_efficiency": 20 if ratios["ROCE (%)"] >= 20 else 15 if ratios["ROCE (%)"] >= 15 else 8 if ratios["ROCE (%)"] >= 10 else 0,
        "growth": 20 if ratios["Revenue CAGR (%)"] >= 15 and ratios["PAT CAGR (%)"] >= 15 else 15 if ratios["Revenue CAGR (%)"] >= 10 and ratios["PAT CAGR (%)"] >= 10 else 8 if ratios["Revenue CAGR (%)"] >= 5 else 0,
        "balance_sheet": 20 if ratios["Net Debt (Cr)"] <= 0 else 15 if ratios["Debt to Equity"] <= 0.5 else 10 if ratios["Debt to Equity"] <= 1 else 0,
        "cash_quality": 20 if ratios["CFO / PAT Quality Ratio"] >= 1 and ratios["Average CFO / PAT (5Y)"] >= 0.8 else 15 if ratios["CFO / PAT Quality Ratio"] >= 0.7 and ratios["Average CFO / PAT (5Y)"] >= 0.7 else 8 if ratios["Average CFO / PAT (5Y)"] >= 0.5 else 0,
        "governance": 20 if governance_clean else 0,
    }
    score = sum(components.values())
    rating = "INVESTIBLE" if score >= 80 else "WATCHLIST" if score >= 60 else "AVOID"
    return {"score_100": score, "rating": rating, "components": components}


def calculate_pe_valuation(current_price: float, shares_outstanding_cr: float, latest_pat_cr: float, pat_cagr_pct: float, target_pe: float = 25.0, margin_of_safety_pct: float = 20.0) -> Dict[str, Any]:
    if current_price <= 0 or shares_outstanding_cr <= 0 or latest_pat_cr <= 0:
        return {"available": False, "reason": "Valid price, shares outstanding and PAT are required."}
    eps = latest_pat_cr / shares_outstanding_cr
    fair_value = eps * target_pe
    buy_below = fair_value * (1 - margin_of_safety_pct / 100)
    market_cap_cr = current_price * shares_outstanding_cr
    implied_pe = current_price / eps if eps else 0.0
    return {
        "available": True,
        "current_price": round(current_price, 2),
        "market_cap_cr": round(market_cap_cr, 2),
        "eps": round(eps, 2),
        "current_pe": round(implied_pe, 2),
        "target_pe": round(target_pe, 2),
        "fair_value": round(fair_value, 2),
        "margin_of_safety_pct": round(margin_of_safety_pct, 2),
        "buy_below": round(buy_below, 2),
        "upside_to_fair_value_pct": round((fair_value / current_price - 1) * 100, 2),
        "pat_cagr_used_pct": round(pat_cagr_pct, 2),
    }


def determine_final_recommendation(quality: Dict[str, Any], ratios: Dict[str, Any], forensic_clean: bool, valuation: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Deterministic final decision; avoids allowing an LLM to override hard risk rules."""
    if not forensic_clean or ratios["Positive CFO Years"].startswith("0/"):
        return {"verdict": "AVOID", "reason": "Governance/forensic clearance failed or operating cash flow is persistently weak."}

    score = quality["score_100"]
    if score < 60:
        return {"verdict": "AVOID", "reason": "Quality score is below the minimum 60/100 threshold."}

    if valuation and valuation.get("available"):
        price = valuation["current_price"]
        buy_below = valuation["buy_below"]
        fair_value = valuation["fair_value"]
        if score >= 80 and price <= buy_below:
            return {"verdict": "BUY", "reason": "High quality and price is at or below the margin-of-safety level."}
        if price <= fair_value:
            return {"verdict": "WATCHLIST", "reason": "Quality is acceptable, but the price is above the preferred margin-of-safety level."}
        return {"verdict": "WATCHLIST", "reason": "Business quality may be acceptable, but valuation leaves insufficient margin of safety."}

    if score >= 80:
        return {"verdict": "BUY", "reason": "Quality score is at least 80/100 and no hard governance failure was detected."}
    return {"verdict": "WATCHLIST", "reason": "Fundamentals are acceptable but do not meet the high-conviction quality threshold."}
