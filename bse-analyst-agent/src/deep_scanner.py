import csv
import os
from typing import Any, Dict, List

from src.nse_downloader import NSEDownloader
from src.doc_parser import FinancialDocParser
from src.financial_tools import (
    calculate_fundamental_ratios,
    calculate_quality_score,
    calculate_pe_valuation,
    determine_final_recommendation,
)
from src.agent import AnalysisOrchestrator


def analyze_candidate(row: Dict[str, Any], orchestrator: AnalysisOrchestrator | None = None) -> Dict[str, Any]:
    symbol = str(row.get("symbol", "")).strip().upper()
    if not symbol:
        return {**row, "status": "ERROR", "error": "Missing symbol"}

    try:
        pdf_path = NSEDownloader().download_report(symbol)
        if not pdf_path:
            return {**row, "status": "NO_REPORT", "error": "Annual report unavailable"}

        parser = FinancialDocParser(pdf_path)
        sections = parser.extract_critical_sections()
        ai = orchestrator or AnalysisOrchestrator()

        forensics = ai.audit_forensics(sections["auditor_report"], sections["notes"])
        history = ai.extract_metrics_payload(sections["financial_statements"])
        ratios = calculate_fundamental_ratios(history)

        governance_clean = (
            forensics.audit_opinion_type.lower().startswith("unmodified")
            and forensics.contingent_liability_risk.lower().startswith("low")
            and forensics.related_party_risk.lower().startswith("low")
            and not forensics.forensic_red_flags
        )
        quality = calculate_quality_score(ratios, governance_clean=governance_clean)

        price = float(row["price"]) if row.get("price") not in (None, "") else None
        market_cap = float(row["market_cap_cr"]) if row.get("market_cap_cr") not in (None, "") else None
        shares_cr = market_cap / price if price and price > 0 and market_cap and market_cap > 0 else None
        valuation = {"available": False, "reason": "Price/market-cap unavailable."}
        if price is not None and shares_cr is not None:
            valuation = calculate_pe_valuation(
                price,
                shares_cr,
                history.years[-1].pat,
                ratios["PAT CAGR (%)"],
                target_pe=20.0,
                margin_of_safety_pct=30.0,
            )

        memo = ai.run_investment_committee(forensics, ratios, quality, valuation)
        recommendation = determine_final_recommendation(quality, ratios, governance_clean, valuation)

        return {
            **row,
            "status": "ANALYZED",
            "verdict": recommendation["verdict"],
            "decision_reason": recommendation["reason"],
            "quality_score": quality["score_100"],
            "ai_conviction": memo.conviction_score,
            "governance_clean": governance_clean,
            "pat_cagr_pct": ratios.get("PAT CAGR (%)"),
            "revenue_cagr_pct": ratios.get("Revenue CAGR (%)"),
            "roce_pct": ratios.get("ROCE (%)"),
            "roe_pct": ratios.get("ROE (%)"),
            "cfo_pat": ratios.get("CFO/PAT"),
            "debt_equity": ratios.get("Debt/Equity"),
            "fair_value": valuation.get("fair_value"),
            "buy_below": valuation.get("buy_below"),
            "risk_flags": ";".join(forensics.forensic_red_flags or []),
            "thesis": memo.executive_summary.strip(),
        }
    except Exception as exc:
        return {**row, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}


def run_deep_scan(input_csv: str = "./outputs/small_microcap_universe.csv", top: int = 10, output_dir: str = "./outputs") -> List[Dict[str, Any]]:
    if not os.path.exists(input_csv):
        raise FileNotFoundError(f"Stage-1 CSV not found: {input_csv}. Run --scan first.")

    with open(input_csv, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    ai = AnalysisOrchestrator()
    results = [analyze_candidate(row, ai) for row in rows]
    analyzed = [r for r in results if r.get("status") == "ANALYZED"]
    analyzed.sort(key=lambda r: (r.get("verdict") == "BUY", float(r.get("quality_score") or 0), float(r.get("ai_conviction") or 0)), reverse=True)
    selected = analyzed[:top]

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "small_microcap_deep_analysis.csv")
    fields = sorted({key for row in results for key in row.keys()})
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    print(f"[+] Stage-2 analyzed: {len(analyzed)}/{len(rows)}")
    print(f"[+] Saved full deep-analysis results: {path}")
    print("\nTOP SMALL/MICRO-CAP RESEARCH SHORTLIST")
    print("-" * 110)
    for i, row in enumerate(selected, 1):
        print(f"{i:>2}. {row['symbol']:<15} {row.get('market_cap_category',''):<9} {row.get('verdict',''):<10} Score {row.get('quality_score')}  PAT CAGR {row.get('pat_cagr_pct')}%  ROCE {row.get('roce_pct')}%  Fair ₹{row.get('fair_value')}")
    return selected
