"""
rank_traders.py

Rank wallets by realized PnL on resolved 15m BTC/ETH/SOL Up/Down markets,
using cached trades and gamma-resolved winners.

PnL model (taker fills, cash-flow basis):
  - BUY of token X at price p, size s:  cost = +p*s ; if X==winner, payout = +1*s else 0
  - SELL of token X at price p, size s: receive = +p*s ; if X==winner, deliver = -1*s
  pnl = received - paid + payout - delivered

Equivalent per-fill PnL contribution:
  side=BUY,  X==winner:  +s*(1-p)
  side=BUY,  X!=winner:  -s*p
  side=SELL, X==winner:  -s*(1-p)
  side=SELL, X!=winner:  +s*p

Usage:
    python scripts/rank_traders.py [--top 30] [--min-trades 200] [--metric pnl]
"""
from __future__ import annotations
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

CACHE = Path("cache/trades")
META = CACHE / "_meta.csv"
GAMMA_WIN = CACHE / "_meta_gamma_winners.csv"
OUT = Path("logs/trader_rankings.csv")
OUT.parent.mkdir(parents=True, exist_ok=True)


def load_winners():
    return {r["slug"]: r["gamma_winner"] for r in csv.DictReader(open(GAMMA_WIN, encoding="utf-8"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--min-trades", type=int, default=100)
    ap.add_argument("--metric", choices=["pnl", "winrate", "volume", "ev_per_dollar"], default="pnl")
    args = ap.parse_args()

    winners = load_winners()
    if not winners:
        print("No gamma winners cached. Run discover_15m_markets.py first.")
        return

    meta = list(csv.DictReader(open(META, encoding="utf-8")))
    stats = defaultdict(lambda: {
        "pnl": 0.0, "volume": 0.0, "n_trades": 0,
        "n_buys": 0, "n_sells": 0,
        "win_dollars": 0.0, "loss_dollars": 0.0,
        "n_markets": set(),
    })
    n_markets_used = 0
    n_trades_seen = 0

    for m in meta:
        slug = m["slug"]
        winner = winners.get(slug)
        if not winner:
            continue
        f = CACHE / f"{slug}.json"
        if not (f.exists() and f.stat().st_size > 2):
            continue
        try:
            trades = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        n_markets_used += 1
        for t in trades:
            try:
                addr = (t.get("proxyWallet") or "").lower()
                if not addr:
                    continue
                side = t.get("side", "")
                asset = str(t.get("asset", ""))
                size = float(t.get("size", 0) or 0)
                price = float(t.get("price", 0) or 0)
            except Exception:
                continue
            if size <= 0 or price <= 0:
                continue
            won = (asset == winner)
            if side == "BUY":
                pnl = size * (1.0 - price) if won else -size * price
                cash = price * size
            elif side == "SELL":
                pnl = -size * (1.0 - price) if won else size * price
                cash = price * size
            else:
                continue
            s = stats[addr]
            s["pnl"] += pnl
            s["volume"] += cash
            s["n_trades"] += 1
            if side == "BUY":
                s["n_buys"] += 1
            else:
                s["n_sells"] += 1
            if pnl >= 0:
                s["win_dollars"] += cash
            else:
                s["loss_dollars"] += cash
            s["n_markets"].add(slug)
            n_trades_seen += 1

    print(f"Markets used: {n_markets_used}  trades scored: {n_trades_seen}  unique wallets: {len(stats)}")

    rows = []
    for addr, s in stats.items():
        if s["n_trades"] < args.min_trades:
            continue
        denom = s["win_dollars"] + s["loss_dollars"]
        ev_per_dollar = s["pnl"] / denom if denom else 0.0
        winrate_d = s["win_dollars"] / denom if denom else 0.0
        rows.append({
            "address": addr,
            "pnl": s["pnl"],
            "volume": s["volume"],
            "n_trades": s["n_trades"],
            "n_markets": len(s["n_markets"]),
            "winrate_dollar": winrate_d,
            "ev_per_dollar": ev_per_dollar,
            "buy_share": s["n_buys"] / s["n_trades"] if s["n_trades"] else 0,
        })
    print(f"Wallets with >= {args.min_trades} trades: {len(rows)}")

    key = {"pnl": "pnl", "winrate": "winrate_dollar",
           "volume": "volume", "ev_per_dollar": "ev_per_dollar"}[args.metric]
    rows.sort(key=lambda r: r[key], reverse=True)

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["address", "pnl", "volume", "n_trades", "n_markets",
                            "winrate_dollar", "ev_per_dollar", "buy_share"])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {OUT}")

    print(f"\nTop {args.top} by {args.metric}:")
    print(f"{'rank':>4} {'address':<44} {'pnl':>12} {'vol':>12} {'n':>6} {'mkts':>6} {'win$%':>7} {'EV/$':>7} {'buy%':>6}")
    for i, r in enumerate(rows[:args.top], 1):
        print(f"{i:>4} {r['address']:<44} {r['pnl']:>12,.2f} {r['volume']:>12,.0f} "
              f"{r['n_trades']:>6} {r['n_markets']:>6} {r['winrate_dollar']:>7.2%} "
              f"{r['ev_per_dollar']:>7.2%} {r['buy_share']:>6.2%}")


if __name__ == "__main__":
    main()
