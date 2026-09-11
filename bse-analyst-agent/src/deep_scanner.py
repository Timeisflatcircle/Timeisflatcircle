import csv
import os
from collections import Counter
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
from src.corporate_risk import assess_corporate_risk, extract_announcements_from_rows
from src.nse_corporate_filings import NSECorporateFilings


ANALYZED_REQUIRED_FIELDS = (
    "verdict",
    "quality_score",
    "ai_conviction",
    "thesis",
)


def _write_results_csv(results: List[Dict[str, Any]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fields = sorted({key for row in results for key in row.keys()})
    if not fields:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


def _is_complete_analysis(result: Dict[str, Any]) -> bool:
    """Only count a row as fully analyzed when the final research payload exists."""
    return (
        result.get("status") == "ANALYZED"
        and all(result.get(field) not in (None, "") for field in ANALYZED_REQUIRED_FIELDS)
    )


def analyze_candidate(
    row: Dict[str, Any],
    orchestrator: AnalysisOrchestrator | None = None,
    filings_client: NSECorporateFilings | None = None,
    live_filings: bool = True,
) -> Dict[str, Any]:
    symbol = str(row.get("symbol", "")).strip().upper()
    if not symbol:
        return {**row, "status": "ERROR", "stage": "INPUT", "error": "Missing symbol"}

    try:
        filing_data: dict[str, Any] = {"announcements": [], "pit_risk_rows": [], "shareholding": {}}
        if live_filings:
            client = filings_client or NSECorporateFilings()
            filing_data = client.cached_risk_inputs(symbol)

        promoter_holding = filing_data.get("promoter_holding_pct")
        promoter_pledge = filing_data.get("promoter_pledge_pct")
        promoter_change = filing_data.get("promoter_change_pct")
        if promoter_holding is None:
            promoter_holding = row.get("promoter_holding_pct")
        if promoter_pledge is None:
            promoter_pledge = row.get("promoter_pledge_pct")
        if promoter_change is None:
            promoter_change = row.get("promoter_change_pct")

        corporate = assess_corporate_risk(
            promoter_holding_pct=promoter_holding,
            promoter_pledge_pct=promoter_pledge,
            promoter_change_pct=promoter_change,
            auditor_status=row.get("auditor_status"),
            related_party_risk=row.get("related_party_risk"),
            announcements=extract_announcements_from_rows(
                [*filing_data.get("announcements", []), *filing_data.get("pit_risk_rows", [])]
            ),
        )
        if corporate.hard_fail:
            return {
                **row,
                "status": "CORPORATE_RISK_REJECT",
                "stage": "CORPORATE_RISK",
                "verdict": "AVOID",
                "corporate_risk_score": corporate.risk_score,
                "governance_grade": corporate.governance_grade,
                "corporate_risk_flags": ";".join(corporate.risk_flags),
                "corporate_data_gaps": ";".join(corporate.data_gaps),
                "promoter_holding_pct": promoter_holding,
                "promoter_pledge_pct": promoter_pledge,
                "promoter_change_pct": promoter_change,
                "shareholding_as_on": filing_data.get("shareholding", {}).get("as_on_date"),
                "shareholding_xbrl_url": filing_data.get("shareholding", {}).get("xbrl_url"),
                "filing_source": filing_data.get("source", "NSE"),
                "error": "Rejected before deep analysis due to a hard corporate-risk signal",
            }

        pdf_path = NSEDownloader().download_report(symbol)
        if not pdf_path:
            return {**row, "status": "NO_REPORT", "stage": "FILING", "error": "Annual report unavailable"}

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
            and corporate.governance_grade in {"A", "B"}
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

        result = {
            **row,
            "status": "ANALYZED",
            "stage": "COMPLETE",
            "verdict": recommendation["verdict"],
            "decision_reason": recommendation["reason"],
            "quality_score": quality["score_100"],
            "ai_conviction": memo.conviction_score,
            "governance_clean": governance_clean,
            "corporate_risk_score": corporate.risk_score,
            "governance_grade": corporate.governance_grade,
            "corporate_risk_flags": ";".join(corporate.risk_flags),
            "corporate_data_gaps": ";".join(corporate.data_gaps),
            "promoter_holding_pct": promoter_holding,
            "promoter_pledge_pct": promoter_pledge,
            "promoter_change_pct": promoter_change,
            "shareholding_as_on": filing_data.get("shareholding", {}).get("as_on_date"),
            "shareholding_xbrl_url": filing_data.get("shareholding", {}).get("xbrl_url"),
            "filing_source": filing_data.get("source", "NSE"),
            "pat_cagr_pct": ratios.get("PAT CAGR (%)"),
            "revenue_cagr_pct": ratios.get("Revenue CAGR (%)"),
            "roce_pct": ratios.get("ROCE (%)"),
            "roe_pct": ratios.get("ROE (%)"),
            "cfo_pat": ratios.get("CFO / PAT Quality Ratio"),
            "debt_equity": ratios.get("Debt to Equity"),
            "fair_value": valuation.get("fair_value"),
            "buy_below": valuation.get("buy_below"),
            "risk_flags": ";".join(forensics.forensic_red_flags or []),
            "thesis": memo.executive_summary.strip(),
        }
        if not _is_complete_analysis(result):
            return {
                **result,
                "status": "ERROR",
                "stage": "VALIDATION",
                "error": "Analysis returned an incomplete final payload",
            }
        return result
    except Exception as exc:
        return {
            **row,
            "status": "ERROR",
            "stage": "EXCEPTION",
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_deep_scan(
    input_csv: str = "./outputs/small_microcap_universe.csv",
    top: int = 10,
    deep_limit: int = 20,
    output_dir: str = "./outputs",
    live_filings: bool = True,
) -> List[Dict[str, Any]]:
    if not os.path.exists(input_csv):
        raise FileNotFoundError(f"Stage-1 CSV not found: {input_csv}. Run --scan first.")

    with open(input_csv, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))[:deep_limit]

    ai = AnalysisOrchestrator()
    filings = NSECorporateFilings() if live_filings else None
    results: List[Dict[str, Any]] = []
    path = os.path.join(output_dir, "small_microcap_deep_analysis.csv")

    print(f"[*] Stage-2 starting: {len(rows)} candidates | live filings={'ON' if live_filings else 'OFF'}")
    for index, row in enumerate(rows, 1):
        symbol = str(row.get("symbol", "")).strip().upper() or "<missing>"
        print(f"\n[*] Stage-2 {index}/{len(rows)}: {symbol}")
        result = analyze_candidate(row, ai, filings, live_filings=live_filings)
        results.append(result)
        status = result.get("status", "UNKNOWN")
        print(f"    -> {status} | stage={result.get('stage', '')} | {result.get('error', '')}")
        _write_results_csv(results, path)

    analyzed = [r for r in results if _is_complete_analysis(r)]
    analyzed.sort(
        key=lambda r: (
            r.get("verdict") == "BUY",
            float(r.get("quality_score") or 0),
            float(r.get("ai_conviction") or 0),
        ),
        reverse=True,
    )
    selected = analyzed[:top]
    counts = Counter(r.get("status", "UNKNOWN") for r in results)

    print(f"\n[+] Stage-2 candidates processed: {len(rows)}")
    print(f"[+] Stage-2 fully analyzed: {len(analyzed)}")
    print("[+] Stage-2 status summary: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    if counts.get("ERROR"):
        print("[!] Error details:")
        for result in results:
            if result.get("status") == "ERROR":
                print(f"    - {result.get('symbol', '<missing>')}: {result.get('stage')} -> {result.get('error')}")
    if counts.get("CORPORATE_RISK_REJECT"):
        print("[!] Corporate-risk rejects are intentionally excluded from 'fully analyzed'.")

    print(f"[+] Live NSE filing checks: {'ON' if live_filings else 'OFF'}")
    print(f"[+] Saved checkpoint/final deep-analysis results: {path}")
    print("\nTOP SMALL/MICRO-CAP RESEARCH SHORTLIST")
    print("-" * 110)
    for i, row in enumerate(selected, 1):
        print(f"{i:>2}. {row['symbol']:<15} {row.get('market_cap_category',''):<9} {row.get('verdict',''):<10} Score {row.get('quality_score')}  Gov {row.get('governance_grade')}  Fair ₹{row.get('fair_value')}")
    return selected
