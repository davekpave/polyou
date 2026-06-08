"""
Enriched selectivity sweep — slices on regime, dominant_recent_gate, spread_bps,
top-of-book depth, and pvr_block_ratio_20, in addition to symbol/rr/price.

Reuses the dedup logic from selectivity_sweep_dedup but only considers rows
with the post-rotation enriched schema (regime is non-null).
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

SRC = Path("logs/rr_blocks_resolved.csv")
MIN_N = 15  # raise the bar slightly so we don't chase 8-row outliers


def load() -> pd.DataFrame:
    df = pd.read_csv(SRC)
    df = df.dropna(subset=["would_have_won", "snapshot_price", "signal_rr",
                           "window_start_ts"]).copy()
    df["ts"] = pd.to_datetime(df["ts_iso"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"])

    # Restrict to enriched rows (post-rotation schema where regime is populated).
    if "regime" in df.columns:
        df = df[df["regime"].notna() & (df["regime"].astype(str).str.len() > 0)].copy()

    df = df.sort_values(["symbol", "window_start_ts", "snapshot_price"])
    df = df.groupby(["symbol", "window_start_ts"], as_index=False).first()

    df["date"] = df["ts"].dt.date
    df["won"] = df["would_have_won"].astype(int)
    p = df["snapshot_price"].astype(float)
    df["ev_per_dollar"] = np.where(df["won"] == 1, (1.0 - p) / p, -1.0)

    # Coerce numeric enrichment columns where present.
    for c in ("spread_bps", "pvr_block_ratio_20", "best_ask_size", "best_bid_size"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def stats(sl: pd.DataFrame) -> dict:
    if sl.empty:
        return {"n": 0}
    days = sl["date"].nunique()
    n = len(sl)
    per_day = sl.groupby("date").agg(n=("won", "size"),
                                     wr=("won", "mean"),
                                     ev=("ev_per_dollar", "sum"))
    busy = per_day[per_day["n"] >= 2]
    if n >= 2:
        loo_max = sl.drop(index=sl["ev_per_dollar"].idxmax())["ev_per_dollar"].mean()
        loo_min = sl.drop(index=sl["ev_per_dollar"].idxmin())["ev_per_dollar"].mean()
    else:
        loo_max = loo_min = float("nan")
    return {
        "n": n,
        "days": days,
        "n/day": round(n / days, 1) if days else 0,
        "wr": round(sl["won"].mean(), 4),
        "mean_ev": round(sl["ev_per_dollar"].mean(), 5),
        "total_ev": round(sl["ev_per_dollar"].sum(), 2),
        "worst_day_ev": round(busy["ev"].min(), 2) if not busy.empty else None,
        "ev_drop_best": round(loo_max, 5) if loo_max == loo_max else None,
        "ev_drop_worst": round(loo_min, 5) if loo_min == loo_min else None,
    }


def show(rows, sort="mean_ev"):
    df = pd.DataFrame(rows)
    df = df[df["n"] >= MIN_N]
    if df.empty:
        print("(no slices with n >=", MIN_N, ")")
        return
    df = df.sort_values(sort, ascending=False)
    cols = ["filter", "n", "days", "n/day", "wr", "mean_ev", "total_ev",
            "worst_day_ev", "ev_drop_best", "ev_drop_worst"]
    cols = [c for c in cols if c in df.columns]
    print(df[cols].to_string(index=False))
    print()


def main():
    df = load()
    span = (df["ts"].max() - df["ts"].min()).total_seconds() / 86400.0
    print(f"Loaded {len(df):,} ENRICHED deduped trades over {span:.2f} days "
          f"({df['ts'].min()} -> {df['ts'].max()})")
    print(f"Per symbol: {df['symbol'].value_counts().to_dict()}")
    print(f"Baseline: WR={df['won'].mean():.4f}  mean EV/$={df['ev_per_dollar'].mean():+.5f}  "
          f"total={df['ev_per_dollar'].sum():+.2f}\n")

    # --- 1. By regime, per-symbol + ALL ---
    print("=" * 100)
    print("BY REGIME (per symbol, then ALL)")
    print("=" * 100)
    rows = []
    for sym in ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"]:
        for reg in df["regime"].dropna().unique():
            sl = df[(df["symbol"] == sym) & (df["regime"] == reg)]
            s = stats(sl); s["filter"] = f"{sym} regime={reg}"; rows.append(s)
    for reg in df["regime"].dropna().unique():
        sl = df[df["regime"] == reg]
        s = stats(sl); s["filter"] = f"ALL regime={reg}"; rows.append(s)
    show(rows)

    # --- 2. By dominant_recent_gate, per-symbol + ALL ---
    print("=" * 100)
    print("BY DOMINANT_RECENT_GATE (per symbol, then ALL)")
    print("=" * 100)
    rows = []
    for sym in ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"]:
        for g in df["dominant_recent_gate"].dropna().unique():
            sl = df[(df["symbol"] == sym) & (df["dominant_recent_gate"] == g)]
            s = stats(sl); s["filter"] = f"{sym} gate={g}"; rows.append(s)
    for g in df["dominant_recent_gate"].dropna().unique():
        sl = df[df["dominant_recent_gate"] == g]
        s = stats(sl); s["filter"] = f"ALL gate={g}"; rows.append(s)
    show(rows)

    # --- 3. Regime x gate (ALL symbols) ---
    print("=" * 100)
    print("REGIME x DOMINANT_RECENT_GATE (ALL symbols)")
    print("=" * 100)
    rows = []
    for reg in df["regime"].dropna().unique():
        for g in df["dominant_recent_gate"].dropna().unique():
            sl = df[(df["regime"] == reg) & (df["dominant_recent_gate"] == g)]
            s = stats(sl); s["filter"] = f"regime={reg} gate={g}"; rows.append(s)
    show(rows)

    # --- 4. Regime x symbol (BTC/ETH/SOL detail) ---
    print("=" * 100)
    print("REGIME x SYMBOL detail (sorted by mean_ev)")
    print("=" * 100)
    rows = []
    for sym in ["BTCUSD", "ETHUSD", "SOLUSD"]:
        for reg in df["regime"].dropna().unique():
            for g in df["dominant_recent_gate"].dropna().unique():
                sl = df[(df["symbol"] == sym) & (df["regime"] == reg)
                        & (df["dominant_recent_gate"] == g)]
                s = stats(sl); s["filter"] = f"{sym} {reg} gate={g}"; rows.append(s)
    show(rows)

    # --- 5. spread_bps buckets ---
    if "spread_bps" in df.columns and df["spread_bps"].notna().any():
        print("=" * 100)
        print("BY SPREAD_BPS BUCKET (ALL symbols)")
        print("=" * 100)
        try:
            df["spread_bucket"] = pd.qcut(df["spread_bps"], q=4,
                                          duplicates="drop", labels=False)
            rows = []
            for b in sorted(df["spread_bucket"].dropna().unique()):
                sl = df[df["spread_bucket"] == b]
                lo = sl["spread_bps"].min(); hi = sl["spread_bps"].max()
                s = stats(sl); s["filter"] = f"spread_bps Q{int(b)} [{lo:.0f}-{hi:.0f}]"
                rows.append(s)
            show(rows)
        except Exception as e:
            print(f"spread bucket failed: {e}")

    # --- 6. pvr_block_ratio_20 buckets ---
    if "pvr_block_ratio_20" in df.columns and df["pvr_block_ratio_20"].notna().any():
        print("=" * 100)
        print("BY PVR_BLOCK_RATIO_20 BUCKET (ALL symbols)")
        print("=" * 100)
        try:
            df["pvr_bucket"] = pd.qcut(df["pvr_block_ratio_20"], q=4,
                                       duplicates="drop", labels=False)
            rows = []
            for b in sorted(df["pvr_bucket"].dropna().unique()):
                sl = df[df["pvr_bucket"] == b]
                lo = sl["pvr_block_ratio_20"].min(); hi = sl["pvr_block_ratio_20"].max()
                s = stats(sl); s["filter"] = f"pvr Q{int(b)} [{lo:.2f}-{hi:.2f}]"
                rows.append(s)
            show(rows)
        except Exception as e:
            print(f"pvr bucket failed: {e}")

    # --- 7. Best of best: BTC restricted further by regime/gate/spread ---
    btc = df[df["symbol"] == "BTCUSD"].copy()
    if not btc.empty and "spread_bps" in btc.columns:
        print("=" * 100)
        print("[BTCUSD] regime x gate x (spread<=median)")
        print("=" * 100)
        med = btc["spread_bps"].median()
        rows = []
        for reg in btc["regime"].dropna().unique():
            for g in btc["dominant_recent_gate"].dropna().unique():
                for tag, mask in (("spread<=med", btc["spread_bps"] <= med),
                                  ("spread>med",  btc["spread_bps"] >  med)):
                    sl = btc[(btc["regime"] == reg)
                             & (btc["dominant_recent_gate"] == g)
                             & mask]
                    s = stats(sl)
                    s["filter"] = f"BTC {reg} gate={g} {tag} (med={med:.0f})"
                    rows.append(s)
        show(rows)


if __name__ == "__main__":
    main()
