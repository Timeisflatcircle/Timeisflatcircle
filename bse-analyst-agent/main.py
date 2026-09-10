import argparse
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
from src.financial_tools import calculate_fundamental_ratios, calculate_quality_score, calculate_pe_valuation, determine_final_recommendation
from src.agent import AnalysisOrchestrator


def save_summary_to_notepad(symbol, forensics, ratios, quality, valuation, recommendation, memo, output_dir="./outputs"):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filepath = os.path.join(output_dir, f"{symbol.upper()}_Investment_Summary_{timestamp}.txt")
    divider, sub = "=" * 70, "-" * 70

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"{divider}\nFIVE-YEAR EQUITY RESEARCH INVESTMENT MEMO\n")
        f.write(f"Company: {symbol.upper()} | Date: {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}\n{divider}\n\n")
        f.write(f"[FINAL VERDICT]: {recommendation['verdict']}\n")
        f.write(f"[DETERMINISTIC QUALITY SCORE]: {quality['score_100']} / 100\n")
        f.write(f"[AI THESIS CONVICTION]: {memo.conviction_score} / 10\n")
        f.write(f"[GOVERNANCE]: {'PASSED' if memo.governance_clearance else 'FAILED / REVIEW'}\n")
        f.write(f"[DECISION LOGIC]: {recommendation['reason']}\n\n")

        f.write(f"{sub}\nEXECUTIVE THESIS\n{sub}\n{memo.executive_summary.strip()}\n\n")
        f.write(f"{sub}\nFIVE-YEAR FUNDAMENTALS\n{sub}\n")
        for metric, value in ratios.items():
            if metric != "hurdles_passed":
                f.write(f"  • {metric:<30}: {value}\n")
        f.write("\nHurdles:\n")
        for check, passed in ratios.get("hurdles_passed", {}).items():
            f.write(f"  • {check.replace('_', ' ').title():<30}: {'PASS [✓]' if passed else 'FAIL [X]'}\n")

        f.write(f"\n{sub}\nQUALITY SCORE\n{sub}\n")
        for component, points in quality["components"].items():
            f.write(f"  • {component.replace('_', ' ').title():<30}: {points:>2} / 20\n")
        f.write(f"  TOTAL: {quality['score_100']} / 100\n")

        f.write(f"\n{sub}\nVALUATION\n{sub}\n")
        if valuation.get("available"):
            for key, value in valuation.items():
                if key != "available":
                    f.write(f"  • {key.replace('_', ' ').title():<30}: {value}\n")
        else:
            f.write(f"  • {valuation.get('reason', 'Not calculated.')}\n")

        f.write(f"\n{sub}\nFORENSIC & GOVERNANCE\n{sub}\n")
        f.write(f"  • Audit Opinion             : {forensics.audit_opinion_type}\n")
        f.write(f"  • Contingent Liability Risk : {forensics.contingent_liability_risk}\n")
        f.write(f"  • Related Party Risk        : {forensics.related_party_risk}\n\n")
        f.write("  Key Audit Matters:\n")
        for item in forensics.key_audit_matters or ["None specified."]:
            f.write(f"    - {item}\n")
        f.write("\n  Forensic Red Flags:\n")
        for item in forensics.forensic_red_flags or ["None detected."]:
            f.write(f"    ! {item}\n")

        f.write(f"\n{sub}\nFINANCIAL STRENGTHS\n{sub}\n")
        for item in memo.financial_strengths:
            f.write(f"  [+] {item}\n")
        f.write(f"\n{sub}\nCRITICAL RISKS\n{sub}\n")
        for item in memo.critical_risks:
            f.write(f"  [-] {item}\n")
        f.write(f"\n{divider}\nEnd of Report\n")
    return filepath


def main(symbol, price=None, shares_cr=None, target_pe=25.0, mos=20.0):
    symbol = symbol.upper().strip()
    print(f"\n==========================================\n Starting V2 NSE Analysis Agent | {symbol}\n==========================================\n")

    pdf_path = NSEDownloader().download_report(symbol)
    if not pdf_path:
        print(f"[!] Could not download annual report for {symbol}. Exiting.")
        sys.exit(1)

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

    valuation = {"available": False, "reason": "Supply --price and --shares-cr to calculate transparent P/E fair value."}
    if price is not None and shares_cr is not None:
        valuation = calculate_pe_valuation(price, shares_cr, history.years[-1].pat, ratios["PAT CAGR (%)"], target_pe, mos)

    print("[*] Generating investment thesis...")
    memo = orchestrator.run_investment_committee(forensics, ratios, quality, valuation)
    recommendation = determine_final_recommendation(quality, ratios, governance_clean, valuation)
    memo.verdict = recommendation["verdict"]

    print("\n" + "=" * 60)
    print(f"FINAL VERDICT: {recommendation['verdict']}")
    print(f"QUALITY SCORE: {quality['score_100']}/100")
    print(f"AI THESIS CONVICTION: {memo.conviction_score}/10")
    if valuation.get("available"):
        print(f"FAIR VALUE: ₹{valuation['fair_value']} | BUY BELOW: ₹{valuation['buy_below']}")
    print("=" * 60)

    saved_file = save_summary_to_notepad(symbol, forensics, ratios, quality, valuation, recommendation, memo)
    print(f"[+] Summary saved: {saved_file}")

    try:
        os.system(f'notepad "{saved_file}"')
    except Exception:
        pass


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Five-year Indian equity research agent")
    cli.add_argument("symbol", nargs="?", default="TCS", help="NSE symbol, e.g. TCS")
    cli.add_argument("--price", type=float, help="Current share price in INR for valuation")
    cli.add_argument("--shares-cr", type=float, help="Current shares outstanding in crore shares")
    cli.add_argument("--target-pe", type=float, default=25.0, help="Target P/E multiple")
    cli.add_argument("--mos", type=float, default=20.0, help="Margin of safety percentage")
    args = cli.parse_args()
    main(args.symbol, args.price, args.shares_cr, args.target_pe, args.mos)
