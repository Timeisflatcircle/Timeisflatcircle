import os
import sys
import warnings
from datetime import datetime
from dotenv import load_dotenv

# Suppress minor SDK warnings
warnings.filterwarnings("ignore", message=r".*automatic function calling \(AFC\).*")

# Ensure root directory is always on sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

load_dotenv()

from src.nse_downloader import NSEDownloader
from src.doc_parser import FinancialDocParser
from src.financial_tools import calculate_fundamental_ratios
from src.agent import AnalysisOrchestrator


def save_summary_to_notepad(symbol: str, forensics, calculated_ratios: dict, memo, output_dir: str = "./outputs") -> str:
    """Writes the analysis result into a formatted text file for Notepad reference."""
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{symbol.upper()}_Investment_Summary_{timestamp}.txt"
    filepath = os.path.join(output_dir, filename)

    divider = "=" * 70
    sub_divider = "-" * 70

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"{divider}\n")
        f.write(f"           ANNUAL REPORT INVESTMENT MEMO & SUMMARY\n")
        f.write(f"           Company: {symbol.upper()} | Date: {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}\n")
        f.write(f"{divider}\n\n")

        # 1. Final Recommendation Box
        f.write(f"[FINAL VERDICT]: {memo.verdict.upper()}\n")
        f.write(f"[CONVICTION SCORE]: {memo.conviction_score} / 10\n")
        f.write(f"[GOVERNANCE STATUS]: {'CLEAN / PASSED' if memo.governance_clearance else 'RED FLAGS / FAILED'}\n\n")

        # 2. Executive Thesis
        f.write(f"{sub_divider}\n")
        f.write("EXECUTIVE SUMMARY & THESIS:\n")
        f.write(f"{sub_divider}\n")
        f.write(f"{memo.executive_summary.strip()}\n\n")

        # 3. Fundamental Metrics & Hurdles
        f.write(f"{sub_divider}\n")
        f.write("KEY CALCULATED FINANCIAL METRICS (Ind AS Normalized):\n")
        f.write(f"{sub_divider}\n")
        for metric, value in calculated_ratios.items():
            if metric != "hurdles_passed":
                f.write(f"  • {metric:<28}: {value}\n")
        
        f.write("\nHurdle Checks:\n")
        hurdles = calculated_ratios.get("hurdles_passed", {})
        for check, passed in hurdles.items():
            status = "PASS [✓]" if passed else "FAIL [X]"
            f.write(f"  • {check.replace('_', ' ').title():<28}: {status}\n")
        f.write("\n")

        # 4. Forensic & Auditor Findings
        f.write(f"{sub_divider}\n")
        f.write("FORENSIC & GOVERNANCE AUDIT:\n")
        f.write(f"{sub_divider}\n")
        f.write(f"  • Audit Opinion Type        : {forensics.audit_opinion_type}\n")
        f.write(f"  • Contingent Liability Risk  : {forensics.contingent_liability_risk}\n")
        f.write(f"  • Related Party Risk         : {forensics.related_party_risk}\n")
        
        f.write("\n  Key Audit Matters (KAM):\n")
        if forensics.key_audit_matters:
            for kam in forensics.key_audit_matters:
                f.write(f"    - {kam}\n")
        else:
            f.write("    - None specified.\n")

        f.write("\n  Forensic Red Flags Identified:\n")
        if forensics.forensic_red_flags:
            for flag in forensics.forensic_red_flags:
                f.write(f"    ! [ALERT] {flag}\n")
        else:
            f.write("    - None detected.\n")
        f.write("\n")

        # 5. Strengths & Catalysts
        f.write(f"{sub_divider}\n")
        f.write("KEY FINANCIAL STRENGTHS & MOATS:\n")
        f.write(f"{sub_divider}\n")
        for s in memo.financial_strengths:
            f.write(f"  [+] {s}\n")
        f.write("\n")

        # 6. Critical Risks
        f.write(f"{sub_divider}\n")
        f.write("CRITICAL RISKS & DOWNSIDE TRIGGERS:\n")
        f.write(f"{sub_divider}\n")
        for r in memo.critical_risks:
            f.write(f"  [-] {r}\n")
        f.write("\n")
        f.write(f"{divider}\n")
        f.write("End of Report\n")

    return filepath


def main(symbol: str):
    symbol = symbol.upper().strip()
    print(f"\n==========================================")
    print(f" Starting NSE Analysis Agent | Symbol: {symbol}")
    print(f"==========================================\n")
    
    # 1. Download filing from NSE
    downloader = NSEDownloader()
    pdf_path = downloader.download_report(symbol)
    if not pdf_path:
        print(f"[!] Could not download annual report for symbol {symbol}. Exiting.")
        sys.exit(1)

    # 2. Parse high-conviction sections
    print("\n[*] Extracting key sections with PyMuPDF...")
    parser = FinancialDocParser(pdf_path)
    sections = parser.extract_critical_sections()

    # 3. Agent Execution (Gemini)
    orchestrator = AnalysisOrchestrator(model_name="gemini-3.6-flash")
    
    # Phase A: Forensic Audit
    print("\n[*] Running Forensic Governance Audit...")
    forensics = orchestrator.audit_forensics(
        auditor_text=sections["auditor_report"],
        notes_text=sections["notes"]
    )

    # Phase B: Quantitative Metrics & Math
    print("\n[*] Extracting Statement Values & Computing Financial Ratios...")
    raw_metrics = orchestrator.extract_metrics_payload(sections["financial_statements"])
    calculated_ratios = calculate_fundamental_ratios(raw_metrics)

    # Phase C: Final Committee Verdict
    print("\n[*] Convening Investment Committee...")
    memo = orchestrator.run_investment_committee(forensics, calculated_ratios)
    
    # Print quick terminal summary
    print("\n" + "=" * 55)
    print(f"FINAL VERDICT: {memo.verdict.upper()} (Conviction: {memo.conviction_score}/10)")
    print(f"Governance Clearance: {'PASSED' if memo.governance_clearance else 'FAILED'}")
    print("=" * 55)

    # 4. Save to Summary Notepad file
    saved_file = save_summary_to_notepad(symbol, forensics, calculated_ratios, memo)
    print(f"\n[+] Summary file saved successfully:")
    print(f"    --> {saved_file}")

    # Optional: Automatically open it in Notepad on Windows
    try:
        os.system(f'notepad "{saved_file}"')
    except Exception:
        pass


if __name__ == "__main__":
    target_symbol = sys.argv[1] if len(sys.argv) > 1 else "TCS"
    main(target_symbol)