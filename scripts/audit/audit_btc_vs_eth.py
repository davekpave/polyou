"""Audit actual win/loss outcomes per symbol via Polymarket Gamma API."""
import csv
import json
import sys
import time
import requests
from collections import defaultdict

GAMMA = "https://gamma-api.polymarket.com/events?slug={}"


def load_filled():
    rows = []
    with open("logs/execution_log.csv") as f:
        r = csv.DictReader(f)
        for row in r:
            # Header/data are misaligned: "filled" lives in the slope_z_24h column.
            if row.get("slope_z_24h") != "filled":
                continue
            try:
                rows.append({
                    "ts": float(row["timestamp"]),
                    "symbol": row["symbol"],
                    "side": row["side"].upper(),
                    "slug": row["contract_slug"],
                    "entry": float(row["snapshot_price"]),
                })
            except Exception:
                pass
    return rows


def resolve(slug):
    try:
        r = requests.get(GAMMA.format(slug), timeout=10)
        m = r.json()[0]["markets"][0]
    except Exception as e:
        return None, f"err:{e}"
    closed = m.get("closed", False)
    if not closed:
        return None, "open"
    outcomes = m.get("outcomes", [])
    prices = m.get("outcomePrices", [])
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            pass
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            pass
    for i, p in enumerate(prices):
        if str(p) == "1":
            return outcomes[i].upper(), "closed"
    return None, "closed_no_winner"


def main():
    trades = load_filled()
    print(f"Loaded {len(trades)} filled trades.\n")
    cutoff_48h = 1777292100  # 08:15 ET 04-27

    per_symbol_all = defaultdict(lambda: {"w": 0, "l": 0, "open": 0, "err": 0})
    per_symbol_48h = defaultdict(lambda: {"w": 0, "l": 0, "open": 0, "err": 0})
    detail_rows = []

    for t in trades:
        winner, status = resolve(t["slug"])
        if status == "open":
            outcome = "PENDING"
            per_symbol_all[t["symbol"]]["open"] += 1
            if t["ts"] >= cutoff_48h:
                per_symbol_48h[t["symbol"]]["open"] += 1
        elif winner is None:
            outcome = f"ERR ({status})"
            per_symbol_all[t["symbol"]]["err"] += 1
            if t["ts"] >= cutoff_48h:
                per_symbol_48h[t["symbol"]]["err"] += 1
        else:
            won = winner == t["side"]
            outcome = "WIN" if won else "LOSS"
            key = "w" if won else "l"
            per_symbol_all[t["symbol"]][key] += 1
            if t["ts"] >= cutoff_48h:
                per_symbol_48h[t["symbol"]][key] += 1
        detail_rows.append((t["ts"], t["symbol"], t["side"], t["slug"], outcome, winner or "-"))
        time.sleep(0.15)  # gentle on API

    print(f"{'TS':>12}  {'SYM':6}  {'SIDE':4}  {'SLUG':38}  {'WINNER':6}  OUTCOME")
    for r in detail_rows:
        print(f"{r[0]:>12.0f}  {r[1]:6}  {r[2]:4}  {r[3]:38}  {r[5]:6}  {r[4]}")

    def fmt(label, d):
        decided = d["w"] + d["l"]
        wr = (d["w"] / decided * 100) if decided else 0.0
        print(f"  {label:8}  W={d['w']}  L={d['l']}  open={d['open']}  err={d['err']}  WR={wr:.1f}% (n={decided})")

    print("\n=== LIFETIME (per symbol) ===")
    for sym in sorted(per_symbol_all):
        fmt(sym, per_symbol_all[sym])

    print("\n=== LAST 48h (since 08:15 ET 04-27) ===")
    for sym in sorted(per_symbol_48h):
        fmt(sym, per_symbol_48h[sym])


if __name__ == "__main__":
    main()
