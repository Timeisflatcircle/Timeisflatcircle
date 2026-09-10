import argparse
import csv
from pathlib import Path

from src.smallcap_scanner import rank_candidates


def read_csv(path: str):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser(description="Deterministic Indian small/micro-cap pre-screen")
    parser.add_argument("csv_file", help="CSV containing market/fundamental screening fields")
    parser.add_argument("--top", type=int, default=25, help="Number of candidates to display")
    args = parser.parse_args()

    ranked = rank_candidates(read_csv(args.csv_file))
    print("SYMBOL | ELIGIBLE | CATEGORY | RISK | SCORE | FLAGS | FAILURES")
    print("-" * 110)
    for row in ranked[:args.top]:
        risk = row["risk"]
        print(
            f"{row.get('symbol', '')} | {row['eligible']} | {row['market_cap_category']} | "
            f"{risk['risk_band']} | {risk['risk_score_100']}/100 | "
            f"{','.join(risk['flags']) or '-'} | {','.join(row['failures']) or '-'}"
        )


if __name__ == "__main__":
    main()
