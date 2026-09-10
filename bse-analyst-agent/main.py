import argparse
import json
import os
import sys
import warnings
from datetime import datetime
from dotenv import load_dotenv

warnings.filterwarnings("ignore", message=r".*automatic function calling \(AFC\).*")
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
load_dotenv()

from src.nse_downloader import NSEDownloader
from src.doc_parser import FinancialDocParser
from src.financial_tools import (
    calculate_fundamental_ratios,
    calculate_quality_score,
    calculate_pe_valuation,
)
from src.agent import AnalysisOrchestrator


def save_summary_to_notepad(
    symbol: str,
    forensics,
    calculated_ratios: dict,
    quality_score: dict,
    valuation: dict,
    memo,
    output_dir: str = "./outputs",
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filepath = os.path.join(output_dir, f"{symbol.upper()}_Investment_Summary_{timestamp}.txt")
    divider = "=" * 70
    sub = "-" * 70

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"{divider}\n")
        f.write("           FIVE-YEAR EQUITY RESEARCH INVESTMENT MEMO\n")
        f.write(f"           Company: {symbol.upper()} | Date: {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}\n")
        f.write(f"{divider}\n\n")
        f.write(f"[FINAL VERDICT]: {memo.verdict.upper()}\n")
        f.write(f"[AI CONVICTION]: {memo.conviction_score} / 10\n")
        f.write(f"[DETERMINISTIC QUALITY SCORE]: {quality_score['score_100']} / 100 ({quality_score['rating']})\n")
        f.write(f"[GOVERNANCE]: {'PASSED' if memo.governance_clearance else 'FAILED / REVIEW'}\n\n")

        f.write(f"{sub}\nEXECUTIVE THESIS\n{sub}\n{memo.executive_summary.strip()}\n\n")

        f.write(f"{sub}\nFIVE-YEAR FUNDAMENTALS\n{sub}\n")
        for metric, value in calculated_ratios.items():
            if metric != "hurdles_passed":
                f.write(f"  • {metric:<30}: {value}\n")
        f.write("\nHurdles:\n")
        for check, passed in calculated_ratios.get("hurdles_passed", {}).items():
            f.write(f"  • {check.replace('_', ' ').title():<30}: {'PASS [✓]' if passed else 'FAIL [X]'}\n")
        f.write("\n")

        f.write(f"{sub}\nDETERMINISTIC QUALITY SCORE\n{sub}\n")
        for component, points in quality_score["components"].items():
            f.write(f"  • {component.replace('_', ' ').title():<30}: {points:>2} / 20\n")
        f.write(f"  TOTAL: {quality_score['score_100']} / 100\n\n")

        f.write(f"{sub}\nVALUATION\n{sub}\n")
        if valuation.get("available"):
            for key, value in valuation.items():
                if key != "available":
                    f.write(f"  • {key.replace('_', ' ').title():<30}: {value}\n")
        else:
            f.write(f"  • Not calculated: {valuation.get('reason', 'Market price inputs not supplied.')}\n")
        f.write("\n")

        f.write(f"{sub}\nFORENSIC & GOVERNANCE AUDIT\n{sub}\n")
        f.write(f"  • Audit Opinion             : {forensics.audit_opinion_type}\n")
        f.write(f"  • Contingent Liability Risk : {forensics.contingent_liability_risk}\n")
        f.write(f"  • Related Party Risk        : {forensics.related_party_risk}\n\n")
        f.write("  Key Audit Matters:\n")
        for item in forensics.key_audit_matters or ["None specified."]:
            f.write(f"    - {item}\n")
        f.write("\n  Forensic Red Flags:\n")
        for item in forensics.forensic_red_flags or ["None detected."]:
            f.write(f"    ! {item}\n")
        f.write("\n")

        f.write(f"{sub}\nFINANCIAL STRENGTHS\n{sub}\n")
        for item in memo.financial_strengths:
            f.write(f"  [+] {item}\n")
        f.write(f"\n{sub}\nCRITICAL RISKS\n{sub}\n")
        for item in memo.critical_risks:
            f.write(f"  [-] {item}\n")

        f.write(f"\n{divider}\nEnd of Report\n")

    return filepath


def main(symbol: str, price: float | None = None, shares_cr: float | None = None, target_pe: float = 25.0, mos: float = 20.0):
    symbol = symbol.upper().strip()
    print(f"\n==========================================")
    print(f" Starting V2 NSE Analysis Agent | {symbol}")
    print(f"==========================================\n")

    downloader = NSEDownloader()
    pdf_path = downloader.download_report(symbol)
    if not pdf_path:
        print(f"[!] Could not download annual report for {symbol}. Exiting.")
        sys.exit(1)

    print("\n[*] Extracting audit, five-year statements and cash flow...")
    parser = FinancialDocParser(pdf_path)
    sections = parser.extract_critical_sections()

    orchestrator = AnalysisOrchestrator()

    print("\n[*] Running forensic governance audit...")
    forensics = orchestrator.audit_forensics(sections["auditor_report"], sections["notes"])

    print("[*] Extracting five-year financial history...")
    history = orchestrator.extract_metrics_payload(sections["financial_statements"])
    ratios = calculate_fundamental_ratios(history)

    governance_clean = (
        forensics.audit_opinion_type.lower().startswith("unmodified")
        and forensics.contingent_liability_risk.lower().startswith("low")
        and forensics.related_party_risk.lower().startswith("low")
        and not forensics.forensic_red_flags
    )
    quality = calculate_quality_score(ratios, governance_clean=governance_clean)

    valuation = {"available": False, "reason": "Supply --price and --shares-cr to calculate P/E fair value."}
    if price is not None and shares_cr is not None:
        valuation = calculate_pe_valuation(
            current_price=price,
            shares_outstanding_cr=shares_cr,
            latest_pat_cr=history.years[-1].pat,
            pat_cagr_pct=ratios["PAT CAGR (%)"],
            target_pe=target_pe,
            margin_of_safety_pct=mos,
        )

    print("[*] Convening investment committee...")
    memo = orchestrator.run_investment_committee(forensics, ratios, quality, valuation)

    print("\n" + "=" * 60)
    print(f"FINAL VERDICT: {memo.verdict.upper()} | AI CONVICTION: {memo.conviction_score}/10")
    print(f"QUALITY SCORE: {quality['score_100']}/100 ({quality['rating']})")
    if valuation.get("available"):
        print(f"FAIR VALUE: ₹{valuation['fair_value']} | BUY BELOW: ₹{valuation['buy_below']}")
    print("=" * 60)

    saved_file = save_summary_to_notepad(symbol, forensics, ratios, quality, valuation, memo)
    print(f"\n[+] Summary saved: {saved_file}")

    try:
        os.system(f'notepad "{saved_file}"')
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Five-year Indian equity research agent")
    parser.add_argument("symbol", nargs="?", default="TCS", help="NSE symbol, e.g. TCS")
    parser.add_argument("--price", type=float, help="Current share price in INR for valuation")
    parser.add_argument("--shares-cr", type=float, help="Current shares outstanding in crore shares")
    parser.add_argument("--target-pe", type=float, default=25.0, help="Target P/E multiple for fair value")
    parser.add_argument("--mos", type=float, default=20.0, help="Margin of safety percentage")
    args = parser.parse_args()
    main(args.symbol, args.price, args.shares_cr, args.target_pe, args.mos)
