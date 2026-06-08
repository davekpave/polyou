"""Audit per-symbol settlements from logs/execution_log.archive.csv.

Archive rows have: timestamp, symbol, side, contract_slug, ... (slug present).
Resolve each via Polymarket Gamma API and tally W/L per symbol.
"""
import csv
import json
import time
import requests
from collections import defaultdict
from datetime import datetime

ARCHIVE = "logs/execution_log.archive.csv"
GAMMA = "https://gamma-api.polymarket.com/events?slug={}"
VALID_SYMBOLS = {"BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"}


def load_rows():
    rows = []
    with open(ARCHIVE, encoding="utf-8") as f:
        rdr = csv.reader(f)
        next(rdr, None)  # skip header (header is short / misaligned, use positional)
        for parts in rdr:
            if len(parts) < 4:
                continue
            ts, sym, side, slug = parts[0], parts[1], parts[2], parts[3]
            if sym not in VALID_SYMBOLS:
                continue
            try:
                ts_f = float(ts)
            except ValueError:
                continue
            if not slug or "-updown-15m-" not in slug:
                continue
            rows.append({"ts": ts_f, "symbol": sym, "side": side, "slug": slug})
    return rows


def resolve(slug, cache):
    if slug in cache:
        return cache[slug]
    try:
        r = requests.get(GAMMA.format(slug), timeout=10)
        data = r.json()
        if not data:
            cache[slug] = (None, "no_event"); return cache[slug]
        m = data[0]["markets"][0]
    except Exception as e:
        cache[slug] = (None, f"err"); return cache[slug]
    if not m.get("closed", False):
        cache[slug] = (None, "open"); return cache[slug]
    outs = m.get("outcomes", [])
    pr = m.get("outcomePrices", [])
    if isinstance(outs, str):
        try: outs = json.loads(outs)
        except: pass
    if isinstance(pr, str):
        try: pr = json.loads(pr)
        except: pass
    for i, p in enumerate(pr):
        if str(p) == "1":
            cache[slug] = (outs[i].upper(), "closed"); return cache[slug]
    cache[slug] = (None, "no_winner"); return cache[slug]


def main():
    rows = load_rows()
    # dedupe by (symbol, slug) - many archive rows may be same trade attempt
    seen = {}
    for r in rows:
        key = (r["symbol"], r["slug"])
        if key not in seen:
            seen[key] = r
    rows = list(seen.values())
    rows.sort(key=lambda r: r["ts"])
    print(f"Loaded {len(rows)} unique (symbol,slug) rows from archive")
    print(f"Date range: {datetime.utcfromtimestamp(rows[0]['ts'])} -> {datetime.utcfromtimestamp(rows[-1]['ts'])} UTC\n")

    cache = {}
    per_sym = defaultdict(lambda: {"w":0,"l":0,"open":0,"err":0})
    detail = []

    for i, r in enumerate(rows, 1):
        winner, status = resolve(r["slug"], cache)
        time.sleep(0.10)
        if status == "open":
            per_sym[r["symbol"]]["open"] += 1; outcome="OPEN"
        elif winner is None:
            per_sym[r["symbol"]]["err"] += 1; outcome=f"ERR({status})"
        else:
            won = winner == r["side"]
            per_sym[r["symbol"]]["w" if won else "l"] += 1
            outcome = "WIN" if won else "LOSS"
        detail.append((r["ts"], r["symbol"], r["side"], r["slug"], winner or "-", outcome))
        if i % 25 == 0:
            print(f"  ... resolved {i}/{len(rows)}")

    print("\n=== ARCHIVE per-symbol ===")
    for sym in sorted(per_sym):
        d = per_sym[sym]
        decided = d["w"] + d["l"]
        wr = d["w"]/decided*100 if decided else 0
        ev_per_trade = (d["w"] * 0.27 + d["l"] * -0.71) / decided if decided else 0
        print(f"  {sym}  W={d['w']:3d} L={d['l']:3d} open={d['open']} err={d['err']}  WR={wr:5.1f}%  n={decided:3d}  EV/trade=${ev_per_trade:+.3f}")

    # detail for SOL/XRP only
    print("\n=== SOL/XRP detail ===")
    for ts, sym, side, slug, win, out in detail:
        if sym in ("SOLUSD","XRPUSD"):
            print(f"  {datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M')}  {sym}  {side}  -> {win:5}  {out}")


if __name__ == "__main__":
    main()
