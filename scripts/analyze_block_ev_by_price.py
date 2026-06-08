"""Quick EV-by-snapshot_price analysis on resolved block CSVs.

Goal: find any (price band, side, symbol) slice where the gates blocked
trades that would have been +EV. If such a slice exists, it's a candidate
for relaxing gates; if not, the gates are correctly avoiding -EV territory.

Read-only. Run anytime:
    .venv\\Scripts\\python.exe scripts\\analyze_block_ev_by_price.py
"""
from __future__ import annotations

import pandas as pd

PATHS = [
    "logs/gate_blocks_resolved.csv",
    "logs/rr_blocks_resolved.csv",
]
BINS = [0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.0]


def main() -> None:
    for path in PATHS:
        print("=" * 72)
        print(path)
        print("=" * 72)
        df = pd.read_csv(path)
        df = df[df["resolved_winner"].isin(["UP", "DOWN"])].copy()
        df["payoff_per_dollar"] = pd.to_numeric(df["payoff_per_dollar"], errors="coerce")
        df["snapshot_price"] = pd.to_numeric(df["snapshot_price"], errors="coerce")
        df = df.dropna(subset=["payoff_per_dollar", "snapshot_price", "side"])
        df["side"] = df["side"].astype(str).str.upper()
        print(f"rows usable: {len(df):,}   overall mean EV/$ = {df['payoff_per_dollar'].mean():+.4f}")
        df["price_bin"] = pd.cut(df["snapshot_price"], BINS, include_lowest=True)

        print("\n--- ALL SIDES, by price bin ---")
        g = df.groupby("price_bin", observed=True)["payoff_per_dollar"].agg(["count", "mean"])
        g["win_rate"] = df.groupby("price_bin", observed=True).apply(
            lambda x: (x["payoff_per_dollar"] > 0).mean()
        )
        print(g.to_string())

        print("\n--- BY SIDE x price bin ---")
        for side in ["UP", "DOWN"]:
            sub = df[df["side"] == side]
            if len(sub) == 0:
                continue
            print(f"  side={side}  n={len(sub):,}  mean_EV={sub['payoff_per_dollar'].mean():+.4f}")
            gs = sub.groupby("price_bin", observed=True)["payoff_per_dollar"].agg(["count", "mean"])
            print(gs.to_string())
            print()

        print("--- BY SYMBOL ---")
        gs = df.groupby("symbol", observed=True)["payoff_per_dollar"].agg(["count", "mean"])
        gs["win_rate"] = df.groupby("symbol", observed=True).apply(
            lambda x: (x["payoff_per_dollar"] > 0).mean()
        )
        print(gs.to_string())

        print("\n--- BY SYMBOL x SIDE ---")
        gs = df.groupby(["symbol", "side"], observed=True)["payoff_per_dollar"].agg(["count", "mean"])
        print(gs.to_string())
        print()

        # Highlight any +EV slice
        print("--- +EV slices (mean EV/$ > 0, n>=50) ---")
        slices = df.groupby(["symbol", "side", "price_bin"], observed=True)["payoff_per_dollar"].agg(["count", "mean"])
        pos = slices[(slices["mean"] > 0) & (slices["count"] >= 50)].sort_values("mean", ascending=False)
        if len(pos):
            print(pos.to_string())
        else:
            print("  (none)")
        print()


if __name__ == "__main__":
    main()
