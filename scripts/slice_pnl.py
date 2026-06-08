"""
Slice the 151 shadow trades by (a) symbol and (b) entry-price bucket,
using on-chain redemption truth from Gamma API for SETTLED_ZERO rows
and the recorded profit_per_share for EXPIRY_BID rows.

Caches gamma responses to logs/gamma_cache.json so re-runs are free.
"""
from __future__ import annotations

import csv
import json
import os
import time
from collections import defaultdict

import requests

SHADOW = "logs/shadow_exits.csv"
CACHE = "logs/gamma_cache.json"
GAMMA = "https://gamma-api.polymarket.com/events?slug={}"


def load_cache() -> dict:
    if os.path.exists(CACHE):
        return json.load(open(CACHE))
    return {}


def save_cache(c: dict) -> None:
    json.dump(c, open(CACHE, "w"))


def gamma_winner(slug: str, cache: dict) -> str | None:
    """Returns 'UP', 'DOWN', or None (open/missing)."""
    if slug in cache:
        return cache[slug]
    try:
        r = requests.get(GAMMA.format(slug), timeout=15)
        m = r.json()[0]["markets"][0]
        if not m.get("closed"):
            cache[slug] = None
            return None
        outcomes = m.get("outcomes", [])
        prices = m.get("outcomePrices", [])
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        if isinstance(prices, str):
            prices = json.loads(prices)
        winner = None
        for i, p in enumerate(prices):
            if str(p) in ("1", "1.0"):
                winner = outcomes[i].upper()
        cache[slug] = winner
    except Exception:
        cache[slug] = None
    time.sleep(0.25)
    return cache[slug]


def true_pnl(row: dict, cache: dict) -> float | None:
    """Real P&L per share. None if unresolved."""
    if row["exit_type"] == "EXPIRY_BID":
        return float(row["profit_per_share"])
    if row["exit_type"] == "SETTLED_ZERO":
        winner = gamma_winner(row["contract_slug"], cache)
        if winner is None:
            return None
        entry = float(row["entry_price"])
        return (1.0 - entry) if winner == row["side"].upper() else -entry
    return None  # unknown exit type


def bucket(p: float) -> str:
    if p < 0.80:
        return "<0.80"
    if p < 0.85:
        return "0.80-0.85"
    if p < 0.90:
        return "0.85-0.90"
    return ">=0.90"


def fmt(rows: list[dict]) -> str:
    if not rows:
        return "(none)"
    pnls = [r["pnl"] for r in rows]
    n = len(pnls)
    total = sum(pnls)
    mean = total / n
    wins = sum(1 for p in pnls if p > 0)
    return f"n={n:3d}  total=${total:+7.2f}  mean=${mean:+.4f}/trade  win%={100*wins/n:4.1f}"


def main() -> None:
    cache = load_cache()
    rows = list(csv.DictReader(open(SHADOW, newline="")))
    enriched = []
    skipped = 0
    for r in rows:
        p = true_pnl(r, cache)
        if p is None:
            skipped += 1
            continue
        enriched.append({
            "symbol": r["symbol"],
            "side": r["side"].upper(),
            "exit_type": r["exit_type"],
            "entry": float(r["entry_price"]),
            "pnl": p,
        })
    save_cache(cache)

    print(f"Resolved rows: {len(enriched)}  (skipped unresolved: {skipped})")
    print(f"Overall: {fmt(enriched)}")
    print()

    print("=" * 70)
    print("BY SYMBOL")
    print("=" * 70)
    by_sym = defaultdict(list)
    for r in enriched:
        by_sym[r["symbol"]].append(r)
    for sym in sorted(by_sym):
        print(f"  {sym:8s} {fmt(by_sym[sym])}")

    print()
    print("=" * 70)
    print("BY ENTRY PRICE BUCKET")
    print("=" * 70)
    by_b = defaultdict(list)
    for r in enriched:
        by_b[bucket(r["entry"])].append(r)
    for b in ("<0.80", "0.80-0.85", "0.85-0.90", ">=0.90"):
        print(f"  {b:11s} {fmt(by_b[b])}")

    print()
    print("=" * 70)
    print("BY SYMBOL x BUCKET (cells with n>=5 only)")
    print("=" * 70)
    by_sb = defaultdict(list)
    for r in enriched:
        by_sb[(r["symbol"], bucket(r["entry"]))].append(r)
    for (sym, b), lst in sorted(by_sb.items()):
        if len(lst) >= 5:
            print(f"  {sym:8s} {b:11s} {fmt(lst)}")

    print()
    print("=" * 70)
    print("BY SIDE (UP vs DOWN)")
    print("=" * 70)
    by_side = defaultdict(list)
    for r in enriched:
        by_side[r["side"]].append(r)
    for s in ("UP", "DOWN"):
        print(f"  {s:6s} {fmt(by_side[s])}")


if __name__ == "__main__":
    main()
