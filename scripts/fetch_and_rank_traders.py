"""
fetch_and_rank_traders.py

Fetches and ranks top Polymarket traders in 15m crypto Up/Down markets by realized PnL, win rate, and volume.

- Fetches recent resolved 15m crypto Up/Down markets from Gamma API
- Fetches all trades for those markets
- Aggregates by user address
- Computes PnL, win rate, and volume
- Outputs top N traders by metric

Usage: python fetch_and_rank_traders.py [--top N] [--metric pnl|winrate|volume]
"""
import asyncio
import httpx
import argparse
from collections import defaultdict, namedtuple

GAMMA_API = "https://api.gamma.xyz/v1"
MARKET_TYPE = "15m"
CRYPTO_MARKETS = ["BTC", "ETH"]

TraderStats = namedtuple("TraderStats", ["address", "pnl", "wins", "losses", "volume"])

async def fetch_15m_crypto_markets():
    url = f"{GAMMA_API}/markets"
    params = {"interval": MARKET_TYPE, "active": False, "limit": 100, "offset": 0}
    markets = []
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            for m in data:
                if any(sym in m.get("name", "") for sym in CRYPTO_MARKETS):
                    markets.append(m)
            if not resp.json().get("next_cursor"):
                break
            params["offset"] += params["limit"]
    return markets

async def fetch_trades_for_market(market_id):
    url = f"{GAMMA_API}/markets/{market_id}/trades"
    trades = []
    params = {"limit": 100, "offset": 0}
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            trades.extend(data)
            if not resp.json().get("next_cursor"):
                break
            params["offset"] += params["limit"]
    return trades

async def main(top_n=15, metric="pnl"):
    print("Fetching 15m crypto markets...")
    markets = await fetch_15m_crypto_markets()
    print(f"Found {len(markets)} markets.")
    trader_stats = defaultdict(lambda: {"pnl": 0, "wins": 0, "losses": 0, "volume": 0})
    for m in markets:
        market_id = m["id"]
        resolved_outcome = m.get("resolved_outcome")
        if not resolved_outcome:
            continue
        trades = await fetch_trades_for_market(market_id)
        for t in trades:
            addr = t["user_address"]
            side = t["side"]
            amount = float(t["amount"])
            pnl = float(t.get("payout", 0)) - amount if t.get("settled") else 0
            trader_stats[addr]["pnl"] += pnl
            trader_stats[addr]["volume"] += amount
            if t.get("settled") and side == resolved_outcome:
                trader_stats[addr]["wins"] += 1
            elif t.get("settled"):
                trader_stats[addr]["losses"] += 1
    # Convert to list and sort
    stats_list = []
    for addr, stats in trader_stats.items():
        total = stats["wins"] + stats["losses"]
        winrate = stats["wins"] / total if total else 0
        stats_list.append({
            "address": addr,
            "pnl": stats["pnl"],
            "winrate": winrate,
            "volume": stats["volume"]
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
    asyncio.run(main(top_n=args.top, metric=args.metric))
