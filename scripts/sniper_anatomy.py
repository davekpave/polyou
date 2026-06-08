"""
sniper_anatomy.py

For top-N OOS-validated leaders, characterize their fills in the final
window before resolution. Bucket by seconds-to-expiry and price.

Usage:
    python scripts/sniper_anatomy.py [--top 100] [--train-days 60]
"""
from __future__ import annotations
import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean

CACHE = Path("cache/trades")
META = CACHE / "_meta.csv"
GAMMA_WIN = CACHE / "_meta_gamma_winners.csv"
TOP = Path("logs/oos_top_traders.csv")
SLUG_RE = re.compile(r"^(btc|eth|sol)-updown-15m-(\d+)$")
MARKET_LEN = 900


def slug_open_ts(slug):
    m = SLUG_RE.match(slug)
    return int(m.group(2)) if m else None


def slug_close_ts(slug):
    m = SLUG_RE.match(slug)
    return int(m.group(2)) + MARKET_LEN if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--train-days", type=int, default=60)
    args = ap.parse_args()

    leaders = set()
    for r in list(csv.DictReader(open(TOP, encoding="utf-8")))[: args.top]:
        leaders.add(r["address"].lower())
    print(f"Analyzing {len(leaders)} top leaders\n")

    winners = {r["slug"]: r["gamma_winner"]
               for r in csv.DictReader(open(GAMMA_WIN, encoding="utf-8"))}
    meta = list(csv.DictReader(open(META, encoding="utf-8")))
    close_list = [slug_close_ts(m["slug"]) for m in meta if slug_close_ts(m["slug"])]
    t_min = min(close_list)
    split_ts = t_min + int(args.train_days * 86400)

    # TTE buckets (seconds remaining until close); negative = post-close settlement
    TTE_BUCKETS = [
        ("post-close", -60,    0),  # trade after close (settlement)
        ("0-2s",          0,    2),
        ("2-5s",          2,    5),
        ("5-10s",         5,   10),
        ("10-30s",       10,   30),
        ("30-60s",       30,   60),
        ("60-180s",      60,  180),
        ("3-15m",       180,  900),
    ]

    # Side x TTE x outcome aggregates
    by_tte = defaultdict(lambda: {
        "n": 0, "n_buy": 0, "n_sell": 0,
        "n_won": 0, "vol": 0.0, "pnl": 0.0,
        "buy_won": 0, "buy_lost": 0,
        "sell_won": 0, "sell_lost": 0,
        "buy_prices_won": [], "buy_prices_lost": [],
    })

    n_fills = 0
    for m in meta:
        slug = m["slug"]
        winner = winners.get(slug)
        if not winner:
            continue
        close_ts = slug_close_ts(slug)
        if close_ts is None or close_ts < split_ts:
            continue
        f = CACHE / f"{slug}.json"
        if not (f.exists() and f.stat().st_size > 2):
            continue
        try:
            trades = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for t in trades:
            try:
                addr = (t.get("proxyWallet") or "").lower()
                if addr not in leaders:
                    continue
                ts = int(t.get("timestamp", 0) or 0)
                side = t.get("side", "")
                asset = str(t.get("asset", ""))
                size = float(t.get("size", 0) or 0)
                price = float(t.get("price", 0) or 0)
            except Exception:
                continue
            if size <= 0 or price <= 0 or side not in ("BUY", "SELL"):
                continue
            tte = close_ts - ts
            if tte < -60 or tte > 900:
                # outside [open-grace, close]; ignore
                continue
            won = (asset == winner)
            if side == "BUY":
                pnl = size * (1.0 - price) if won else -size * price
            else:
                pnl = -size * (1.0 - price) if won else size * price
            cash = size * price
            for label, lo, hi in TTE_BUCKETS:
                if lo <= tte < hi:
                    s = by_tte[label]
                    s["n"] += 1
                    if side == "BUY":
                        s["n_buy"] += 1
                        if won:
                            s["buy_won"] += 1
                            s["buy_prices_won"].append(price)
                        else:
                            s["buy_lost"] += 1
                            s["buy_prices_lost"].append(price)
                    else:
                        s["n_sell"] += 1
                        if won:
                            s["sell_won"] += 1
                        else:
                            s["sell_lost"] += 1
                    if won: s["n_won"] += 1
                    s["vol"] += cash
                    s["pnl"] += pnl
                    break
            n_fills += 1

    print(f"Total leader fills (test period, tte<=15m): {n_fills:,}\n")

    print(f"{'TTE':<9} {'n':>10} {'%':>6} {'buy%':>6} {'win%':>6} "
          f"{'pnl':>14} {'vol':>14} {'EV/$':>7} "
          f"{'buy@won_avg':>12} {'buy@lost_avg':>12}")
    total = sum(s["n"] for s in by_tte.values()) or 1
    for label, _, _ in TTE_BUCKETS:
        s = by_tte[label]
        if s["n"] == 0:
            print(f"{label:<9} {0:>10}")
            continue
        ev = s["pnl"] / s["vol"] if s["vol"] else 0
        bw = mean(s["buy_prices_won"]) if s["buy_prices_won"] else 0
        bl = mean(s["buy_prices_lost"]) if s["buy_prices_lost"] else 0
        print(f"{label:<9} {s['n']:>10,} {100*s['n']/total:>5.1f}% "
              f"{100*s['n_buy']/s['n']:>5.1f}% "
              f"{100*s['n_won']/s['n']:>5.1f}% "
              f"{s['pnl']:>14,.0f} {s['vol']:>14,.0f} {ev:>6.2%} "
              f"{bw:>12.4f} {bl:>12.4f}")

    # Cumulative pnl share
    print("\nCumulative share of leader PnL & volume by TTE bucket (top→bot of table):")
    cum_pnl = 0.0
    cum_vol = 0.0
    tot_pnl = sum(s["pnl"] for s in by_tte.values())
    tot_vol = sum(s["vol"] for s in by_tte.values())
    for label, _, _ in TTE_BUCKETS:
        s = by_tte[label]
        cum_pnl += s["pnl"]
        cum_vol += s["vol"]
        print(f"  thru {label:<9}: pnl={cum_pnl:>12,.0f} ({cum_pnl/tot_pnl:6.1%})  "
              f"vol={cum_vol:>12,.0f} ({cum_vol/tot_vol:6.1%})")


if __name__ == "__main__":
    main()
