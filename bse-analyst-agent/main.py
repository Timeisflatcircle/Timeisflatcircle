import argparse
import csv
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
from src.nse_universe import NSEUniverse
from src.smallcap_scanner import SmallMicrocapConfig, classify_market_cap
from src.deep_scanner import run_deep_scan


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
            if metric != "hurdles_passed": f.write(f"  • {metric:<30}: {value}\n")
        f.write("\nHurdles:\n")
        for check, passed in ratios.get("hurdles_passed", {}).items(): f.write(f"  • {check.replace('_', ' ').title():<30}: {'PASS [✓]' if passed else 'FAIL [X]'}\n")
        f.write(f"\n{sub}\nQUALITY SCORE\n{sub}\n")
        for component, points in quality["components"].items(): f.write(f"  • {component.replace('_', ' ').title():<30}: {points:>2} / 20\n")
        f.write(f"  TOTAL: {quality['score_100']} / 100\n")
        f.write(f"\n{sub}\nVALUATION\n{sub}\n")
        if valuation.get("available"):
            for key, value in valuation.items():
                if key != "available": f.write(f"  • {key.replace('_', ' ').title():<30}: {value}\n")
        else: f.write(f"  • {valuation.get('reason', 'Not calculated.')}\n")
        f.write(f"\n{sub}\nFORENSIC & GOVERNANCE\n{sub}\n")
        f.write(f"  • Audit Opinion             : {forensics.audit_opinion_type}\n")
        f.write(f"  • Contingent Liability Risk : {forensics.contingent_liability_risk}\n")
        f.write(f"  • Related Party Risk        : {forensics.related_party_risk}\n\n")
        f.write("  Key Audit Matters:\n")
        for item in forensics.key_audit_matters or ["None specified."]: f.write(f"    - {item}\n")
        f.write("\n  Forensic Red Flags:\n")
        for item in forensics.forensic_red_flags or ["None detected."]: f.write(f"    ! {item}\n")
        f.write(f"\n{sub}\nFINANCIAL STRENGTHS\n{sub}\n")
        for item in memo.financial_strengths: f.write(f"  [+] {item}\n")
        f.write(f"\n{sub}\nCRITICAL RISKS\n{sub}\n")
        for item in memo.critical_risks: f.write(f"  [-] {item}\n")
        f.write(f"\n{divider}\nEnd of Report\n")
    return filepath


def run_universe_scan(refresh=False, top=50, limit=None, output_dir="./outputs"):
    """Stage 1: exchange-level discovery only; not an investment recommendation."""
    cfg = SmallMicrocapConfig(); universe = NSEUniverse()
    print("\n[*] Discovering NSE equity universe...")
    rows = universe.discover(limit=limit, refresh=refresh); candidates = []
    for row in rows:
        market_cap, price, traded_value = row.get("market_cap_cr"), row.get("price"), row.get("avg_daily_value_cr")
        if market_cap is None or price is None or traded_value is None: continue
        category = classify_market_cap(float(market_cap), cfg)
        if category not in ("MICROCAP", "SMALLCAP"): continue
        if float(price) < cfg.min_price or float(traded_value) < cfg.min_daily_traded_value_cr: continue
        candidates.append({**row, "market_cap_category": category})
    candidates.sort(key=lambda x: (0 if x["market_cap_category"] == "MICROCAP" else 1, -float(x["market_cap_cr"]), -float(x["avg_daily_value_cr"])))
    selected = candidates[:top]; os.makedirs(output_dir, exist_ok=True); path = os.path.join(output_dir, "small_microcap_universe.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fields = ["symbol", "company_name", "market_cap_category", "market_cap_cr", "price", "avg_daily_value_cr", "source"]
        writer = csv.DictWriter(fh, fieldnames=fields); writer.writeheader(); writer.writerows({k: row.get(k) for k in fields} for row in selected)
    print(f"[+] NSE rows collected: {len(rows)}"); print(f"[+] Candidates passing market/liquidity filters: {len(candidates)}"); print(f"[+] Saved top {len(selected)} candidates to: {path}")
    print("\nTOP CANDIDATES — Stage 1 only (NOT investment recommendations)"); print("-" * 95)
    for i, row in enumerate(selected, 1): print(f"{i:>2}. {row['symbol']:<15} {row['market_cap_category']:<9} MCap ₹{float(row['market_cap_cr']):>9.0f} Cr  Price ₹{float(row['price']):>8.2f}  Traded ₹{float(row['avg_daily_value_cr']):>7.2f} Cr")
    return selected


def main(symbol, price=None, shares_cr=None, target_pe=25.0, mos=20.0):
    symbol = symbol.upper().strip(); print(f"\n==========================================\n Starting V2 NSE Analysis Agent | {symbol}\n==========================================\n")
    pdf_path = NSEDownloader().download_report(symbol)
    if not pdf_path: print(f"[!] Could not download annual report for {symbol}. Exiting."); sys.exit(1)
    parser = FinancialDocParser(pdf_path); sections = parser.extract_critical_sections(); orchestrator = AnalysisOrchestrator()
    print("\n[*] Running forensic governance audit..."); forensics = orchestrator.audit_forensics(sections["auditor_report"], sections["notes"])
    print("[*] Extracting five-year financial history..."); history = orchestrator.extract_metrics_payload(sections["financial_statements"]); ratios = calculate_fundamental_ratios(history)
    governance_clean = (forensics.audit_opinion_type.lower().startswith("unmodified") and forensics.contingent_liability_risk.lower().startswith("low") and forensics.related_party_risk.lower().startswith("low") and not forensics.forensic_red_flags)
    quality = calculate_quality_score(ratios, governance_clean=governance_clean); valuation = {"available": False, "reason": "Supply --price and --shares-cr to calculate transparent P/E fair value."}
    if price is not None and shares_cr is not None: valuation = calculate_pe_valuation(price, shares_cr, history.years[-1].pat, ratios["PAT CAGR (%)"], target_pe, mos)
    print("[*] Generating investment thesis..."); memo = orchestrator.run_investment_committee(forensics, ratios, quality, valuation); recommendation = determine_final_recommendation(quality, ratios, governance_clean, valuation); memo.verdict = recommendation["verdict"]
    print("\n" + "=" * 60); print(f"FINAL VERDICT: {recommendation['verdict']}"); print(f"QUALITY SCORE: {quality['score_100']}/100"); print(f"AI THESIS CONVICTION: {memo.conviction_score}/10")
    if valuation.get("available"): print(f"FAIR VALUE: ₹{valuation['fair_value']} | BUY BELOW: ₹{valuation['buy_below']}")
    print("=" * 60); saved_file = save_summary_to_notepad(symbol, forensics, ratios, quality, valuation, recommendation, memo); print(f"[+] Summary saved: {saved_file}")
    try: os.system(f'notepad "{saved_file}"')
    except Exception: pass


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Indian equity research agent and small/micro-cap scanner")
    cli.add_argument("symbol", nargs="?", default="TCS", help="NSE symbol for deep analysis")
    cli.add_argument("--scan", action="store_true", help="Stage 1: discover NSE small/micro-cap candidates")
    cli.add_argument("--deep-scan", action="store_true", help="Stage 2: deeply analyze the Stage-1 CSV")
    cli.add_argument("--refresh", action="store_true", help="Refresh the NSE universe cache")
    cli.add_argument("--top", type=int, default=50, help="Stage-1 candidates or Stage-2 shortlist size")
    cli.add_argument("--limit", type=int, help="Limit universe symbols for testing")
    cli.add_argument("--input-csv", default="./outputs/small_microcap_universe.csv", help="Stage-1 CSV for Stage 2")
    cli.add_argument("--price", type=float, help="Current share price for single-stock valuation")
    cli.add_argument("--shares-cr", type=float, help="Shares outstanding in crore for single-stock valuation")
    cli.add_argument("--target-pe", type=float, default=25.0, help="Target P/E multiple")
    cli.add_argument("--mos", type=float, default=20.0, help="Margin of safety percentage")
    args = cli.parse_args()
    if args.deep_scan: run_deep_scan(input_csv=args.input_csv, top=args.top)
    elif args.scan: run_universe_scan(refresh=args.refresh, top=args.top, limit=args.limit)
    else: main(args.symbol, args.price, args.shares_cr, args.target_pe, args.mos)
