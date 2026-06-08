"""
Stress-test the 'buy cheap' conclusion.

Issue 1: Maybe the +8% edge for winners is just survivorship — wallets that
        had positive realized outcomes mechanically have win_rate > avg_buy.

Issue 2: Group ALL significant wallets by avg_buy_price bucket and report
        aggregate P&L. If 'buy cheap' is a real strategy, the low-price
        bucket should have aggregate positive P&L (across all wallets in
        that bucket, not just survivors).

Issue 3: Selection / look-elsewhere — top wallets might be lucky tails.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from collections import defaultdict
from statistics import mean

CACHE = Path("cache/trades")
META = CACHE / "_meta.csv"


def main():
    meta = {r["slug"]: r for r in csv.DictReader(open(META))}

    w = defaultdict(
        lambda: {
            "buy_size": 0.0,
            "buy_size_won": 0.0,
            "buy_notional": 0.0,
            "n_buys": 0,
            "n_trades": 0,
            "markets": set(),
            "pnl": 0.0,
        }
    )

    for slug, m in meta.items():
        winner = m["winner_token"]
        if not winner:
            continue
        f = CACHE / f"{slug}.json"
        if not f.exists():
            continue
        for t in json.loads(f.read_text()):
            wallet = t.get("proxyWallet")
            if not wallet:
                continue
            asset = str(t.get("asset"))
            side = t.get("side")
            try:
                p = float(t.get("price"))
                s = float(t.get("size"))
            except (TypeError, ValueError):
                continue
            won = asset == winner
            d = w[wallet]
            d["n_trades"] += 1
            d["markets"].add(slug)
            if side == "BUY":
                d["n_buys"] += 1
                d["buy_size"] += s
                d["buy_notional"] += p * s
                if won:
                    d["buy_size_won"] += s
                d["pnl"] += (1 - p) * s if won else -p * s
            elif side == "SELL":
                d["pnl"] += (p - 1) * s if won else p * s

    # Significant wallets
    sig = []
    for wallet, d in w.items():
        if d["n_trades"] < 30 or len(d["markets"]) < 5 or d["buy_size"] == 0:
            continue
        sig.append(
            {
                "wallet": wallet,
                "avg_buy": d["buy_notional"] / d["buy_size"],
                "win_rate": d["buy_size_won"] / d["buy_size"],
                "buy_size": d["buy_size"],
                "buy_notional": d["buy_notional"],
                "pnl": d["pnl"],
                "n_buys": d["n_buys"],
            }
        )

    print(f"Significant wallets: {len(sig)}")
    print()

    # === TEST 1: Group by avg_buy_price bucket; aggregate P&L per bucket ===
    print("=== Test 1: Aggregate P&L by avg-buy-price bucket (ALL wallets, not just survivors) ===")
    buckets = [(0.0, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.50),
               (0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.00)]
    print(f"{'price bucket':<14} {'n':>5} {'win%':>4} {'tot_buys':>9} "
          f"{'tot_notion':>12} {'tot_pnl':>11} {'pnl/notional':>13} {'win_rate':>9} {'edge':>7}")
    for lo, hi in buckets:
        g = [r for r in sig if lo <= r["avg_buy"] < hi]
        if not g:
            continue
        n_pos = sum(1 for r in g if r["pnl"] > 0)
        tot_buys = sum(r["n_buys"] for r in g)
        tot_size = sum(r["buy_size"] for r in g)
        tot_notional = sum(r["buy_notional"] for r in g)
        tot_pnl = sum(r["pnl"] for r in g)
        # size-weighted realized win rate within bucket
        wt_win_rate = sum(r["win_rate"] * r["buy_size"] for r in g) / tot_size
        wt_avg_buy = tot_notional / tot_size
        edge = wt_win_rate - wt_avg_buy
        print(f"  [{lo:.2f},{hi:.2f}) {len(g):>5} {100*n_pos/len(g):>3.0f}% "
              f"{tot_buys:>9} {tot_notional:>12,.0f} {tot_pnl:>+11,.0f} "
              f"{100*tot_pnl/tot_notional:>+12.2f}% {100*wt_win_rate:>8.1f}% {100*edge:>+6.2f}%")

    # === TEST 2: Per-trade aggregation (not per-wallet) ===
    # For every BUY trade in our dataset, bucket by trade price; what's avg outcome?
    print()
    print("=== Test 2: Aggregate ALL BUY trades by price (n=trade-level, not wallet-level) ===")
    trade_buckets = defaultdict(lambda: {"n": 0, "size": 0.0, "wins": 0.0, "notional": 0.0})
    for slug, m in meta.items():
        winner = m["winner_token"]
        if not winner:
            continue
        f = CACHE / f"{slug}.json"
        if not f.exists():
            continue
        for t in json.loads(f.read_text()):
            if t.get("side") != "BUY":
                continue
            try:
                p = float(t["price"])
                s = float(t["size"])
            except (TypeError, ValueError, KeyError):
                continue
            asset = str(t.get("asset"))
            won = asset == winner
            # bucket
            key = round(p * 10) / 10  # 0.0, 0.1, ..., 1.0
            b = trade_buckets[key]
            b["n"] += 1
            b["size"] += s
            b["notional"] += p * s
            if won:
                b["wins"] += s
    print(f"{'price ~':>8} {'n_trades':>9} {'tot_size':>10} {'win_rate':>9} {'expected':>9} {'edge':>7} {'pnl_per_$':>10}")
    for key in sorted(trade_buckets.keys()):
        b = trade_buckets[key]
        if b["size"] == 0:
            continue
        win_rate = b["wins"] / b["size"]
        avg_p = b["notional"] / b["size"]
        edge = win_rate - avg_p
        # PnL per $ notional of buys: pay $1 to get $1/avg_p shares; expected payout = (1/avg_p)*win_rate
        pnl_per_dollar = (1 / avg_p) * win_rate - 1
        print(f"  {key:>5.2f}  {b['n']:>9}  {b['size']:>10,.0f}  "
              f"{100*win_rate:>8.1f}%  {100*avg_p:>8.1f}%  {100*edge:>+6.1f}%  "
              f"{100*pnl_per_dollar:>+9.2f}%")


if __name__ == "__main__":
    main()
