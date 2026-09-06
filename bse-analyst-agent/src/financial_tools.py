from pydantic import BaseModel, Field
from typing import Dict, Any

class CompanyFinancialInputs(BaseModel):
    revenue_t: float = Field(description="Current year revenue from operations (INR Cr)")
    revenue_t_minus_1: float = Field(description="Previous year revenue (INR Cr)")
    ebit_t: float = Field(description="Current year Operating Profit / EBIT (INR Cr)")
    pat_t: float = Field(description="Current year Profit After Tax (INR Cr)")
    pat_t_minus_1: float = Field(description="Previous year Profit After Tax (INR Cr)")
    total_debt: float = Field(description="Short term + Long term borrowings (INR Cr)")
    total_equity: float = Field(description="Shareholder's Net Worth / Equity (INR Cr)")
    cash_equivalents: float = Field(description="Cash and liquid bank balances (INR Cr)")
    cfo_t: float = Field(description="Cash flow from operating activities (INR Cr)")
    interest_expense: float = Field(description="Finance costs / interest paid (INR Cr)")

def calculate_fundamental_ratios(data: CompanyFinancialInputs) -> Dict[str, Any]:
    # 1. Capital efficiency
    capital_employed = (data.total_equity + data.total_debt) - data.cash_equivalents
    roce = (data.ebit_t / capital_employed * 100) if capital_employed > 0 else 0.0
    roe = (data.pat_t / data.total_equity * 100) if data.total_equity > 0 else 0.0
    
    # 2. Growth metrics
    rev_growth = ((data.revenue_t - data.revenue_t_minus_1) / data.revenue_t_minus_1 * 100) if data.revenue_t_minus_1 else 0.0
    pat_growth = ((data.pat_t - data.pat_t_minus_1) / data.pat_t_minus_1 * 100) if data.pat_t_minus_1 else 0.0
    
    # 3. Solvency & Cash Conversion
    net_debt = data.total_debt - data.cash_equivalents
    de_ratio = data.total_debt / data.total_equity if data.total_equity else 0.0
    interest_coverage = (data.ebit_t / data.interest_expense) if data.interest_expense > 0 else 999.0
    cfo_to_pat = (data.cfo_t / data.pat_t) if data.pat_t > 0 else 0.0
    
    return {
        "ROCE (%)": round(roce, 2),
        "ROE (%)": round(roe, 2),
        "Revenue YoY Growth (%)": round(rev_growth, 2),
        "PAT YoY Growth (%)": round(pat_growth, 2),
        "Debt to Equity": round(de_ratio, 2),
        "Net Debt (Cr)": round(net_debt, 2),
        "Interest Coverage Ratio": round(interest_coverage, 2),
        "CFO / PAT Quality Ratio": round(cfo_to_pat, 2),
        # Hurdle evaluations
        "hurdles_passed": {
            "roce_above_15": roce >= 15.0,
            "clean_debt": de_ratio <= 1.0 or net_debt <= 0,
            "cash_conversion_sound": cfo_to_pat >= 0.7,
            "healthy_coverage": interest_coverage >= 3.5
        }
    }