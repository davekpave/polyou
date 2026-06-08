"""
Selectivity sweep — DEDUPED per market window.

A "trade" = at most one entry per (symbol, window_start_ts). The bot would
take the first qualifying snapshot in a window, not all of them. So we
collapse the resolved rr_blocks log to one row per window (the snapshot
with the lowest snapshot_price = best entry the window offered while the
rr filter was active).

Then we sweep selectivity over that deduped trade universe.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import numpy as np


SRC = Path("logs/rr_blocks_resolved.csv")


def load_and_dedupe() -> pd.DataFrame:
    df = pd.read_csv(SRC)
    df = df.dropna(subset=["would_have_won", "snapshot_price", "signal_rr",
                           "window_start_ts"]).copy()
    df["ts"] = pd.to_datetime(df["ts_iso"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"])

    # Keep the BEST entry seen during each (symbol, window) — lowest price = highest rr.
    df = df.sort_values(["symbol", "window_start_ts", "snapshot_price"])
    deduped = df.groupby(["symbol", "window_start_ts"], as_index=False).first()

    deduped["date"] = deduped["ts"].dt.date
    deduped["won"] = deduped["would_have_won"].astype(int)
    p = deduped["snapshot_price"].astype(float)
    deduped["ev_per_dollar"] = np.where(deduped["won"] == 1, (1.0 - p) / p, -1.0)
    return deduped


def slice_stats(sl: pd.DataFrame) -> dict:
    if sl.empty:
        return {"n": 0}
    days = sl["date"].nunique()
    n = len(sl)
    wr = sl["won"].mean()
    mean_ev = sl["ev_per_dollar"].mean()
    total_ev = sl["ev_per_dollar"].sum()
    per_day = sl.groupby("date").agg(
        n=("won", "size"), wr=("won", "mean"), ev=("ev_per_dollar", "sum")
    )
    busy = per_day[per_day["n"] >= 2]
    worst_day_wr = float(busy["wr"].min()) if not busy.empty else float("nan")
    worst_day_ev = float(busy["ev"].min()) if not busy.empty else float("nan")
    if n >= 2:
        loo_drop_max = sl.drop(index=sl["ev_per_dollar"].idxmax())["ev_per_dollar"].mean()
        loo_drop_min = sl.drop(index=sl["ev_per_dollar"].idxmin())["ev_per_dollar"].mean()
    else:
        loo_drop_max = loo_drop_min = float("nan")
    return {
        "n": n,
        "days": days,
        "n_per_day": round(n / days, 2) if days else 0,
        "wr": round(wr, 4),
        "mean_ev": round(mean_ev, 5),
        "total_ev": round(total_ev, 2),
        "worst_day_wr": round(worst_day_wr, 4) if worst_day_wr == worst_day_wr else None,
        "worst_day_ev": round(worst_day_ev, 3) if worst_day_ev == worst_day_ev else None,
        "ev_drop_best": round(loo_drop_max, 5) if loo_drop_max == loo_drop_max else None,
        "ev_drop_worst": round(loo_drop_min, 5) if loo_drop_min == loo_drop_min else None,
    }


def fmt(df: pd.DataFrame, sort_by: str = "mean_ev") -> str:
    if df.empty:
        return "(empty)"
    df = df[df["n"] > 0].copy().sort_values(sort_by, ascending=False)
    cols = [
        "filter", "n", "days", "n_per_day", "wr",
        "mean_ev", "total_ev",
        "worst_day_wr", "worst_day_ev",
        "ev_drop_best", "ev_drop_worst",
    ]
    cols = [c for c in cols if c in df.columns]
    return df[cols].to_string(index=False)


def sweep_rr(df: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for t in [round(x, 3) for x in np.arange(0.0, 0.71, 0.025)]:
        sl = df[df["signal_rr"] >= t]
        s = slice_stats(sl)
        s["filter"] = f"{label} rr>={t:.3f}"
        s["threshold"] = t
        rows.append(s)
    return pd.DataFrame(rows)


def sweep_max_price(df: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for p in [round(x, 3) for x in np.arange(0.55, 0.96, 0.025)]:
        sl = df[df["snapshot_price"] <= p]
        s = slice_stats(sl)
        s["filter"] = f"{label} price<={p:.3f}"
        s["threshold"] = p
        rows.append(s)
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-n", type=int, default=10)
    args = parser.parse_args()

    df = load_and_dedupe()
    span = (df["ts"].max() - df["ts"].min()).total_seconds() / 86400.0
    print(f"Loaded {len(df):,} DEDUPED trades over {span:.2f} days "
          f"({df['ts'].min()} -> {df['ts'].max()})")
    print(f"Trades/day raw = {len(df)/max(span,1e-9):.1f}")
    print(f"Per symbol counts:\n{df['symbol'].value_counts().to_string()}\n")
    print(f"Baseline: WR={df['won'].mean():.4f}  mean EV/$={df['ev_per_dollar'].mean():+.5f}  "
          f"total={df['ev_per_dollar'].sum():+.2f}\n")

    # Per-symbol rr sweep
    for sym in ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"]:
        sub = df[df["symbol"] == sym]
        if sub.empty:
            continue
        print("=" * 90)
        print(f"[{sym}] signal_rr threshold sweep ({len(sub)} trades, {sub['date'].nunique()} days)")
        print("=" * 90)
        s = sweep_rr(sub, sym)
        s = s[s["n"] >= args.min_n].sort_values("threshold")
        print(fmt(s, sort_by="threshold"))
        print()

    # All-symbol rr sweep (cross-check)
    print("=" * 90)
    print("[ALL] signal_rr threshold sweep")
    print("=" * 90)
    s = sweep_rr(df, "ALL")
    s = s[s["n"] >= args.min_n].sort_values("threshold")
    print(fmt(s, sort_by="threshold"))
    print()

    # BTC + max_price sweep
    btc = df[df["symbol"] == "BTCUSD"]
    if not btc.empty:
        print("=" * 90)
        print("[BTCUSD] max-price sweep (no rr filter)")
        print("=" * 90)
        s = sweep_max_price(btc, "BTC")
        s = s[s["n"] >= args.min_n].sort_values("threshold")
        print(fmt(s, sort_by="threshold"))
        print()

    # BTC: combined (rr>=X, price<=Y) grid
    print("=" * 90)
    print("[BTCUSD] combined rr x max_price grid (showing positive-EV cells with n>=min_n)")
    print("=" * 90)
    if not btc.empty:
        rows = []
        for rr in [0.05, 0.075, 0.10, 0.125, 0.15, 0.175, 0.20, 0.25]:
            for mp in [0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]:
                sl = btc[(btc["signal_rr"] >= rr) & (btc["snapshot_price"] <= mp)]
                s = slice_stats(sl)
                s["filter"] = f"BTC rr>={rr:.3f} & price<={mp:.2f}"
                rows.append(s)
        grid = pd.DataFrame(rows)
        grid = grid[(grid["n"] >= args.min_n) & (grid["mean_ev"] > 0)]
        print(fmt(grid.sort_values("mean_ev", ascending=False).head(25), sort_by="mean_ev"))


if __name__ == "__main__":
    main()
