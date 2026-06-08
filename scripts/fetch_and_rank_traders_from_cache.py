"""
fetch_and_rank_traders_from_cache.py

Ranks top Polymarket traders in 15m crypto Up/Down markets using local cache/trades/*.json.
- Reads market metadata from _meta.csv
- Reads resolved outcomes from _meta_gamma_winners.csv
- Aggregates per-user PnL, win rate, and volume
- Outputs top N traders by chosen metric

Usage: python fetch_and_rank_traders_from_cache.py [--top N] [--metric pnl|winrate|volume]
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

CACHE = Path("cache/trades")
META = CACHE / "_meta.csv"
GAMMA_WINNERS = CACHE / "_meta_gamma_winners.csv"

# Load market metadata
with open(META, newline='') as f:
    meta = list(csv.DictReader(f))

# Load resolved outcomes
winner_map = {}
with open(GAMMA_WINNERS, newline='') as f:
    for row in csv.DictReader(f):
        winner_map[row['slug']] = row['gamma_winner']

def aggregate_trader_stats():
    trader_stats = defaultdict(lambda: {"pnl": 0, "wins": 0, "losses": 0, "volume": 0})
    for m in meta:
        slug = m['slug']
        if not slug.endswith('15m'):
            continue
        resolved = winner_map.get(slug)
        if not resolved:
            continue
        trade_file = CACHE / f"{slug}.json"
        if not trade_file.exists():
            continue
        with open(trade_file) as f:
            trades = json.load(f)
        for t in trades:
            addr = t.get('user_address') or t.get('address')
            side = str(t.get('outcome') or t.get('side'))
            amount = float(t.get('amount', 0))
            payout = float(t.get('payout', 0))
            settled = t.get('settled', True)  # Assume settled if not present
            pnl = payout - amount if settled else 0
            trader_stats[addr]["pnl"] += pnl
            trader_stats[addr]["volume"] += amount
            if settled and side == resolved:
                trader_stats[addr]["wins"] += 1
            elif settled:
                trader_stats[addr]["losses"] += 1
    return trader_stats

def main(top_n=15, metric="pnl"):
    stats = aggregate_trader_stats()
    stats_list = []
    for addr, s in stats.items():
        total = s["wins"] + s["losses"]
        winrate = s["wins"] / total if total else 0
        stats_list.append({
            "address": addr,
            "pnl": s["pnl"],
            "winrate": winrate,
            "volume": s["volume"]
        })
    stats_list.sort(key=lambda x: x[metric], reverse=True)
    print(f"Top {top_n} traders by {metric}:")
    for i, s in enumerate(stats_list[:top_n], 1):
        print(f"{i:2d}. {s['address']} | PnL: {s['pnl']:.2f} | Winrate: {s['winrate']:.2%} | Volume: {s['volume']:.2f}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=15, help="Number of top traders to show")
    parser.add_argument("--metric", type=str, default="pnl", choices=["pnl", "winrate", "volume"], help="Metric to rank by")
    args = parser.parse_args()
    main(top_n=args.top, metric=args.metric)
