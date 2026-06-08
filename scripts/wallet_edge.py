"""
For each significant wallet, compute realized win-rate of their BUYS:
  win_rate = sum(s where asset==winner and side==BUY) / sum(s where side==BUY)

Test: do top winners just buy cheap (rate ~ avg_buy_price) or do they
pick winners (rate > avg_buy_price)?
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from collections import defaultdict

CACHE = Path("cache/trades")
META = CACHE / "_meta.csv"


def main():
    meta = {r["slug"]: r for r in csv.DictReader(open(META))}

    # wallet -> {buy_size_total, buy_size_winning, buy_notional, n_buys, pnl}
    w = defaultdict(
        lambda: {
            "buy_size": 0.0,
            "buy_size_won": 0.0,
            "buy_notional": 0.0,
            "buy_notional_won": 0.0,
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
                    d["buy_notional_won"] += p * s
                d["pnl"] += (1 - p) * s if won else -p * s
            elif side == "SELL":
                d["pnl"] += (p - 1) * s if won else p * s

    rows = []
    for wallet, d in w.items():
        if d["n_trades"] < 30 or len(d["markets"]) < 5:
            continue
        avg_buy = d["buy_notional"] / d["buy_size"] if d["buy_size"] else None
        win_rate = d["buy_size_won"] / d["buy_size"] if d["buy_size"] else None
        # Edge: realized win-rate vs implied probability (avg buy price)
        edge = (win_rate - avg_buy) if (win_rate is not None and avg_buy is not None) else None
        rows.append(
            {
                "wallet": wallet,
                "pnl": d["pnl"],
                "n_buys": d["n_buys"],
                "buy_size": d["buy_size"],
                "avg_buy_price": avg_buy,
                "win_rate": win_rate,
                "edge": edge,
                "n_markets": len(d["markets"]),
            }
        )

    rows.sort(key=lambda r: r["pnl"], reverse=True)
    print(f"Significant wallets: {len(rows)}\n")

    # Aggregate edge vs avg buy price
    print("--- Top 20 winners: do they pick winners or just buy cheap? ---")
    print(f"{'wallet':<44} {'pnl':>10} {'buys':>5} {'avg_buy':>8} {'win%':>7} {'edge':>7}")
    for r in rows[:20]:
        print(
            f"  {r['wallet']:<42} {r['pnl']:>10.2f} {r['n_buys']:>5} "
            f"{r['avg_buy_price']:>8.4f} {100*r['win_rate']:>6.1f}% {100*r['edge']:>+6.1f}%"
        )
    print()
    print("--- Bottom 20 (losers) ---")
    for r in rows[-20:][::-1]:
        print(
            f"  {r['wallet']:<42} {r['pnl']:>10.2f} {r['n_buys']:>5} "
            f"{r['avg_buy_price']:>8.4f} {100*r['win_rate']:>6.1f}% {100*r['edge']:>+6.1f}%"
        )

    # Group by win/lose and report aggregated edge
    winners = [r for r in rows if r["pnl"] > 0]
    losers = [r for r in rows if r["pnl"] < 0]

    def share_weighted(group, field_num, field_den):
        n = sum(r[field_num] for r in group)
        d = sum(r[field_den] for r in group)
        return n / d if d else None

    print()
    print("--- Aggregated by group (size-weighted) ---")
    for label, g in [("Winners", winners), ("Losers", losers), ("All", rows)]:
        g = [r for r in g if r["avg_buy_price"] is not None and r["win_rate"] is not None]
        n_buys = sum(r["n_buys"] for r in g)
        size = sum(r["buy_size"] for r in g)
        # Weighted avg buy price
        wt_avg_buy = sum(r["avg_buy_price"] * r["buy_size"] for r in g) / size
        wt_win_rate = sum(r["win_rate"] * r["buy_size"] for r in g) / size
        edge = wt_win_rate - wt_avg_buy
        print(
            f"  {label:<10} n={len(g):<4}  buys={n_buys}  "
            f"avg_buy={wt_avg_buy:.4f}  win_rate={wt_win_rate:.4f}  "
            f"edge={100*edge:+.2f}%  total_pnl=${sum(r['pnl'] for r in g):,.0f}"
        )


if __name__ == "__main__":
    main()
