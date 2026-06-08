"""
Selectivity sweep over resolved rr_blocks.

Goal: find filter thresholds where the surviving slice has clean, robust EV.
We do NOT target a trade count. We let the data tell us what the best knee is.

Quality scores explored:
  - signal_rr only
  - signal_rr within entry_price band [a, b)
  - signal_rr per symbol

Per filter we report:
  n, n/day, days_active, WR, mean EV/$, total EV/$,
  worst-day WR (min over days with >= 3 trades), leave-one-out fragility.

Usage:
    python scripts/selectivity_sweep.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import numpy as np


SRC = Path("logs/rr_blocks_resolved.csv")


def load() -> pd.DataFrame:
    df = pd.read_csv(SRC)
    df = df.dropna(subset=["would_have_won", "snapshot_price", "signal_rr"]).copy()
    df["ts"] = pd.to_datetime(df["ts_iso"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"])
    df["date"] = df["ts"].dt.date
    df["won"] = df["would_have_won"].astype(int)
    # EV per $1 staked on the entry side (price = snapshot_price).
    # win  -> (1 - p)/p
    # lose -> -1
    p = df["snapshot_price"].astype(float)
    df["ev_per_dollar"] = np.where(df["won"] == 1, (1.0 - p) / p, -1.0)
    return df


def slice_stats(sl: pd.DataFrame) -> dict:
    if sl.empty:
        return {"n": 0}
    days = sl["date"].nunique()
    n = len(sl)
    wr = sl["won"].mean()
    mean_ev = sl["ev_per_dollar"].mean()
    total_ev = sl["ev_per_dollar"].sum()
    per_day = sl.groupby("date").agg(n=("won", "size"), wr=("won", "mean"), ev=("ev_per_dollar", "sum"))
    busy = per_day[per_day["n"] >= 3]
    worst_day_wr = float(busy["wr"].min()) if not busy.empty else float("nan")
    worst_day_ev = float(busy["ev"].min()) if not busy.empty else float("nan")
    # Leave-one-out fragility on EV: drop the single largest-EV trade, recompute mean.
    if n >= 2:
        max_ev_idx = sl["ev_per_dollar"].idxmax()
        loo_mean = sl.drop(index=max_ev_idx)["ev_per_dollar"].mean()
    else:
        loo_mean = float("nan")
    return {
        "n": n,
        "days": days,
        "n_per_day": round(n / days, 2) if days else 0,
        "wr": round(wr, 4),
        "mean_ev": round(mean_ev, 5),
        "total_ev": round(total_ev, 2),
        "worst_day_wr": round(worst_day_wr, 4) if worst_day_wr == worst_day_wr else None,
        "worst_day_ev": round(worst_day_ev, 3) if worst_day_ev == worst_day_ev else None,
        "loo_mean_ev": round(loo_mean, 5) if loo_mean == loo_mean else None,
    }


def sweep_threshold(df: pd.DataFrame, col: str, thresholds, label: str) -> pd.DataFrame:
    rows = []
    for t in thresholds:
        sl = df[df[col] >= t]
        s = slice_stats(sl)
        s["filter"] = f"{label} >= {t:.3f}"
        s["threshold"] = t
        rows.append(s)
    return pd.DataFrame(rows)


def sweep_band_and_rr(df: pd.DataFrame) -> pd.DataFrame:
    """Sweep entry-price band x signal_rr threshold."""
    bands = [
        (0.00, 0.10),
        (0.05, 0.15),
        (0.10, 0.20),
        (0.15, 0.25),
        (0.20, 0.30),
        (0.25, 0.40),
        (0.30, 0.50),
        (0.40, 0.70),
        (0.50, 1.00),
    ]
    rr_thresholds = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
    rows = []
    for lo, hi in bands:
        band_sl = df[(df["snapshot_price"] >= lo) & (df["snapshot_price"] < hi)]
        if band_sl.empty:
            continue
        for rr in rr_thresholds:
            sl = band_sl[band_sl["signal_rr"] >= rr]
            s = slice_stats(sl)
            s["filter"] = f"price[{lo:.2f},{hi:.2f}) & rr>={rr:.2f}"
            s["band_lo"] = lo
            s["band_hi"] = hi
            s["rr_min"] = rr
            rows.append(s)
    return pd.DataFrame(rows)


def per_symbol_rr(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    rr_thresholds = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40]
    for sym, sub in df.groupby("symbol"):
        for rr in rr_thresholds:
            sl = sub[sub["signal_rr"] >= rr]
            s = slice_stats(sl)
            s["filter"] = f"{sym} rr>={rr:.2f}"
            s["symbol"] = sym
            s["rr_min"] = rr
            rows.append(s)
    return pd.DataFrame(rows)


def fmt(df: pd.DataFrame, sort_by: str = "mean_ev") -> str:
    if df.empty:
        return "(empty)"
    df = df[df["n"] > 0].copy()
    df = df.sort_values(sort_by, ascending=False)
    cols = [
        "filter", "n", "days", "n_per_day", "wr",
        "mean_ev", "loo_mean_ev", "total_ev",
        "worst_day_wr", "worst_day_ev",
    ]
    cols = [c for c in cols if c in df.columns]
    return df[cols].to_string(index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-n", type=int, default=20,
                        help="Minimum slice size to consider (default 20).")
    parser.add_argument("--top", type=int, default=15,
                        help="Top N rows to print per section (default 15).")
    args = parser.parse_args()

    df = load()
    span = (df["ts"].max() - df["ts"].min())
    days_total = max(span.total_seconds() / 86400.0, 1e-9)
    print(f"Loaded {len(df):,} resolved rows over {days_total:.2f} days "
          f"({df['ts'].min()} -> {df['ts'].max()})")
    print(f"Baseline: WR={df['won'].mean():.4f}  mean EV/$={df['ev_per_dollar'].mean():+.5f}  "
          f"total EV/$={df['ev_per_dollar'].sum():+.2f}\n")

    print("=" * 80)
    print("[1] signal_rr threshold sweep (all symbols, all prices)")
    print("=" * 80)
    rr_grid = [round(x, 3) for x in np.arange(0.0, 0.51, 0.025)]
    s1 = sweep_threshold(df, "signal_rr", rr_grid, "rr")
    s1 = s1[s1["n"] >= args.min_n]
    print(fmt(s1.head(args.top * 2), sort_by="mean_ev"))

    print("\n" + "=" * 80)
    print("[2] entry_price band x signal_rr threshold")
    print("=" * 80)
    s2 = sweep_band_and_rr(df)
    s2 = s2[s2["n"] >= args.min_n]
    print("Top by mean EV/$:")
    print(fmt(s2.head(args.top), sort_by="mean_ev"))
    print("\nTop by total EV (weight × edge):")
    print(fmt(s2.head(args.top), sort_by="total_ev"))

    print("\n" + "=" * 80)
    print("[3] per-symbol signal_rr threshold")
    print("=" * 80)
    s3 = per_symbol_rr(df)
    s3 = s3[s3["n"] >= args.min_n]
    print(fmt(s3, sort_by="mean_ev"))

    print("\n" + "=" * 80)
    print("[4] knee table — strictest rr where WR stays >= 0.95 AND mean EV/$ > 0")
    print("=" * 80)
    knee = s1[(s1["wr"] >= 0.95) & (s1["mean_ev"] > 0)].sort_values("threshold", ascending=False)
    print(fmt(knee.head(10), sort_by="threshold"))


if __name__ == "__main__":
    main()
