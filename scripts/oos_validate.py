"""
oos_validate.py

Out-of-sample validation: rank wallets on train period (first 60 days),
measure those rankings' PnL on test period (last 30 days). If top-decile
of train traders earns > median trader on test, the leaderboard has signal.

Usage:
    python scripts/oos_validate.py [--train-days 60] [--min-train-trades 100]
"""
from __future__ import annotations
import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

CACHE = Path("cache/trades")
META = CACHE / "_meta.csv"
GAMMA_WIN = CACHE / "_meta_gamma_winners.csv"

SLUG_RE = re.compile(r"^(btc|eth|sol)-updown-15m-(\d+)$")


def slug_end_ts(slug: str) -> int | None:
    m = SLUG_RE.match(slug)
    return int(m.group(2)) if m else None


def trade_pnl(side: str, asset: str, size: float, price: float, winner: str):
    """Return (pnl, cash_at_risk)."""
    won = (asset == winner)
    if side == "BUY":
        return (size * (1.0 - price) if won else -size * price), price * size
    if side == "SELL":
        return (-size * (1.0 - price) if won else size * price), price * size
    return 0.0, 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-days", type=int, default=60)
    ap.add_argument("--min-train-trades", type=int, default=100)
    ap.add_argument("--min-test-trades", type=int, default=20)
    ap.add_argument("--top-n", type=int, default=100)
    args = ap.parse_args()

    winners = {r["slug"]: r["gamma_winner"]
               for r in csv.DictReader(open(GAMMA_WIN, encoding="utf-8"))}
    meta = list(csv.DictReader(open(META, encoding="utf-8")))

    # Compute split timestamp
    end_ts_list = [slug_end_ts(m["slug"]) for m in meta]
    end_ts_list = [t for t in end_ts_list if t]
    t_min, t_max = min(end_ts_list), max(end_ts_list)
    total_days = (t_max - t_min) / 86400
    split_ts = t_min + int(args.train_days * 86400)
    print(f"Window: {total_days:.1f} days  split @ train-day {args.train_days}")
    print(f"  train: {(split_ts - t_min)/86400:.1f}d  test: {(t_max - split_ts)/86400:.1f}d")

    # Per-wallet stats split by period
    train = defaultdict(lambda: {"pnl": 0.0, "n": 0, "vol": 0.0, "cash_risk": 0.0})
    test = defaultdict(lambda: {"pnl": 0.0, "n": 0, "vol": 0.0, "cash_risk": 0.0})

    n_train_mkts = 0
    n_test_mkts = 0
    for m in meta:
        slug = m["slug"]
        winner = winners.get(slug)
        if not winner:
            continue
        ts = slug_end_ts(slug)
        if ts is None:
            continue
        f = CACHE / f"{slug}.json"
        if not (f.exists() and f.stat().st_size > 2):
            continue
        bucket = train if ts < split_ts else test
        if ts < split_ts:
            n_train_mkts += 1
        else:
            n_test_mkts += 1
        try:
            trades = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for t in trades:
            try:
                addr = (t.get("proxyWallet") or "").lower()
                if not addr:
                    continue
                size = float(t.get("size", 0) or 0)
                price = float(t.get("price", 0) or 0)
                if size <= 0 or price <= 0:
                    continue
                pnl, cash = trade_pnl(t.get("side", ""), str(t.get("asset", "")),
                                      size, price, winner)
            except Exception:
                continue
            s = bucket[addr]
            s["pnl"] += pnl
            s["n"] += 1
            s["vol"] += cash
            s["cash_risk"] += cash

    print(f"Train markets: {n_train_mkts}  Test markets: {n_test_mkts}")
    print(f"Train wallets: {len(train)}  Test wallets: {len(test)}")

    # Eligible wallets: enough trades in BOTH halves
    eligible = []
    for addr, s in train.items():
        if s["n"] < args.min_train_trades:
            continue
        ts_stat = test.get(addr)
        if not ts_stat or ts_stat["n"] < args.min_test_trades:
            continue
        eligible.append((addr, s, ts_stat))
    print(f"Eligible (train>={args.min_train_trades}, test>={args.min_test_trades}): {len(eligible)}")

    if not eligible:
        return

    # Rank by train PnL
    eligible.sort(key=lambda x: x[1]["pnl"], reverse=True)

    def summarize(group, label):
        if not group:
            print(f"  {label}: empty")
            return
        train_pnls = [tr["pnl"] for _, tr, _ in group]
        test_pnls = [te["pnl"] for _, _, te in group]
        test_evpd = [te["pnl"] / te["cash_risk"] if te["cash_risk"] else 0.0
                     for _, _, te in group]
        n_pos = sum(1 for p in test_pnls if p > 0)
        print(f"  {label} (n={len(group)}):  "
              f"train_pnl_sum={sum(train_pnls):>12,.0f}  "
              f"test_pnl_sum={sum(test_pnls):>12,.0f}  "
              f"test_pnl_mean={mean(test_pnls):>9,.1f}  "
              f"test_pnl_median={median(test_pnls):>8,.1f}  "
              f"test_EV/$_mean={mean(test_evpd):>6.2%}  "
              f"pct_test_pos={n_pos/len(group):.1%}")

    n = len(eligible)
    print("\nTrain-rank decile  ->  test PnL behavior:")
    for i in range(10):
        lo, hi = int(i * n / 10), int((i + 1) * n / 10)
        summarize(eligible[lo:hi], f"D{i+1} (rank {lo+1}-{hi})")

    # Top-N specifically
    print(f"\nTop {args.top_n} by train PnL:")
    summarize(eligible[:args.top_n], f"top {args.top_n}")
    print(f"\nBottom {args.top_n} by train PnL:")
    summarize(eligible[-args.top_n:], f"bot {args.top_n}")

    # Spearman rank-corr between train PnL and test PnL
    try:
        from statistics import correlation  # py3.10+
        train_ranks = sorted(range(n), key=lambda i: eligible[i][1]["pnl"])
        test_ranks = sorted(range(n), key=lambda i: eligible[i][2]["pnl"])
        rt = [0] * n
        rte = [0] * n
        for r, idx in enumerate(train_ranks): rt[idx] = r
        for r, idx in enumerate(test_ranks): rte[idx] = r
        print(f"\nSpearman rank-corr(train_pnl, test_pnl) = {correlation(rt, rte):.4f}")
    except Exception as e:
        print(f"(corr unavailable: {e})")

    # Persist top-100
    out = Path("logs/oos_top_traders.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["address", "train_pnl", "train_n", "train_vol",
                    "test_pnl", "test_n", "test_vol", "test_ev_per_dollar"])
        for addr, tr, te in eligible[:args.top_n]:
            ev = te["pnl"] / te["cash_risk"] if te["cash_risk"] else 0
            w.writerow([addr, f"{tr['pnl']:.2f}", tr["n"], f"{tr['vol']:.2f}",
                        f"{te['pnl']:.2f}", te["n"], f"{te['vol']:.2f}", f"{ev:.6f}"])
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
