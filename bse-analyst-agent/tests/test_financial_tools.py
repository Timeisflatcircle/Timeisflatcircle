import unittest

from src.financial_tools import (
    AnnualFinancials,
    CompanyFinancialHistory,
    calculate_fundamental_ratios,
    calculate_quality_score,
    calculate_pe_valuation,
    determine_final_recommendation,
)


class FinancialToolsTests(unittest.TestCase):
    def setUp(self):
        self.history = CompanyFinancialHistory(years=[
            AnnualFinancials(fiscal_year="FY2022", revenue=1000, ebit=180, pat=120, total_debt=100, total_equity=600, cash_equivalents=150, cfo=125, interest_expense=10, capex=40),
            AnnualFinancials(fiscal_year="FY2023", revenue=1120, ebit=205, pat=135, total_debt=90, total_equity=680, cash_equivalents=170, cfo=145, interest_expense=9, capex=45),
            AnnualFinancials(fiscal_year="FY2024", revenue=1260, ebit=230, pat=155, total_debt=80, total_equity=760, cash_equivalents=200, cfo=165, interest_expense=8, capex=50),
            AnnualFinancials(fiscal_year="FY2025", revenue=1420, ebit=260, pat=180, total_debt=70, total_equity=850, cash_equivalents=240, cfo=195, interest_expense=7, capex=55),
            AnnualFinancials(fiscal_year="FY2026", revenue=1600, ebit=300, pat=210, total_debt=60, total_equity=950, cash_equivalents=300, cfo=225, interest_expense=6, capex=60),
        ])

    def test_five_year_ratios(self):
        ratios = calculate_fundamental_ratios(self.history)
        self.assertEqual(ratios["years_analyzed"], 5)
        self.assertGreater(ratios["ROCE (%)"], 15)
        self.assertGreater(ratios["Revenue CAGR (%)"], 10)
        self.assertEqual(ratios["Positive CFO Years"], "5/5")

    def test_score_is_deterministic(self):
        ratios = calculate_fundamental_ratios(self.history)
        score = calculate_quality_score(ratios, governance_clean=True)
        self.assertEqual(score["score_100"], 100)
        self.assertEqual(score["rating"], "INVESTIBLE")

    def test_pe_valuation(self):
        value = calculate_pe_valuation(2000, 100, 210, 10, target_pe=20, margin_of_safety_pct=20)
        self.assertTrue(value["available"])
        self.assertEqual(value["eps"], 2.1)
        self.assertEqual(value["fair_value"], 42.0)
        self.assertEqual(value["buy_below"], 33.6)

    def test_governance_failure_means_avoid(self):
        ratios = calculate_fundamental_ratios(self.history)
        quality = calculate_quality_score(ratios, governance_clean=False)
        decision = determine_final_recommendation(quality, ratios, forensic_clean=False)
        self.assertEqual(decision["verdict"], "AVOID")


if __name__ == "__main__":
    unittest.main()
