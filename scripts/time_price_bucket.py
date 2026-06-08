"""
Bucket BUY trades by:
  (a) time within the 15m window: 0-25%, 25-50%, 50-75%, 75-100%, post-end
  (b) trade price bucket

Report per (time_bucket, price_bucket): n_trades, total_size, win_rate,
expected payout per $1 spent.

If "buy cheap = +EV" is real, it should persist in the early-window
buckets (0-25%, 25-50%) — when nobody yet knows which side is right.
If it only shows up late (75-100% or post-end), it's adverse selection /
post-resolution dust and not exploitable.

Window timing inferred from slug: slug ends with window_start_ts; window_end = start + 900s.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from collections import defaultdict

CACHE = Path("cache/trades")
META = CACHE / "_meta.csv"


def time_bucket(dt_to_end: int, win_len: int = 900) -> str:
    # dt_to_end = ts - window_end (negative pre-end, positive post-end)
    elapsed = win_len + dt_to_end  # seconds since window start
    if dt_to_end >= 0:
        return "post-end"
    if elapsed < 0:
        return "pre-start"  # shouldn't happen often
    pct = elapsed / win_len
    if pct < 0.25:
        return "0-25%"
    if pct < 0.50:
        return "25-50%"
    if pct < 0.75:
        return "50-75%"
    return "75-100%"


def price_bucket(p: float) -> str:
    if p < 0.10:
        return "<0.10"
    if p < 0.25:
        return "0.10-0.25"
    if p < 0.40:
        return "0.25-0.40"
    if p < 0.55:
        return "0.40-0.55"
    if p < 0.70:
        return "0.55-0.70"
    if p < 0.85:
        return "0.70-0.85"
    return ">=0.85"


def main():
    meta = {r["slug"]: r for r in csv.DictReader(open(META))}

    # (time_bucket, price_bucket) -> {n, size, wins, notional}
    cells = defaultdict(lambda: {"n": 0, "size": 0.0, "wins": 0.0, "notional": 0.0})
    # also row totals
    time_totals = defaultdict(lambda: {"n": 0, "size": 0.0, "wins": 0.0, "notional": 0.0})

    for slug, m in meta.items():
        winner = m["winner_token"]
        if not winner:
            continue
        f = CACHE / f"{slug}.json"
        if not f.exists():
            continue
        try:
            window_start = int(slug.rsplit("-", 1)[-1])
        except ValueError:
            continue
        window_end = window_start + 900
        for t in json.loads(f.read_text()):
            if t.get("side") != "BUY":
                continue
            try:
                p = float(t["price"])
                s = float(t["size"])
                ts = int(t["timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            asset = str(t.get("asset"))
            won = asset == winner
            tb = time_bucket(ts - window_end)
            pb = price_bucket(p)
            for d in (cells[(tb, pb)], time_totals[tb]):
                d["n"] += 1
                d["size"] += s
                d["notional"] += p * s
                if won:
                    d["wins"] += s

    time_order = ["pre-start", "0-25%", "25-50%", "50-75%", "75-100%", "post-end"]
    price_order = ["<0.10", "0.10-0.25", "0.25-0.40", "0.40-0.55", "0.55-0.70", "0.70-0.85", ">=0.85"]

    print("=== Per-time-bucket totals ===")
    print(f"{'time':<10} {'n_trades':>9} {'tot_size':>12} {'avg_p':>7} {'win_rate':>9} {'edge':>7} {'EV/$':>9}")
    for tb in time_order:
        d = time_totals[tb]
        if d["size"] == 0:
            continue
        wr = d["wins"] / d["size"]
        avg_p = d["notional"] / d["size"]
        ev_per_dollar = (1 / avg_p) * wr - 1
        print(f"  {tb:<8} {d['n']:>9} {d['size']:>12,.0f} {avg_p:>7.3f} "
              f"{100*wr:>8.1f}% {100*(wr-avg_p):>+6.1f}% {100*ev_per_dollar:>+8.1f}%")

    print()
    print("=== EV per $1 spent, by (time, price) ===")
    print("(blank = no trades; -∞ floor of -100% means total loss)")
    print()
    header = f"{'price\\time':<12}" + "".join(f"{tb:>14}" for tb in time_order if any(cells[(tb, pb)]['size'] for pb in price_order))
    print(header)
    active_times = [tb for tb in time_order if any(cells[(tb, pb)]['size'] for pb in price_order)]
    for pb in price_order:
        cols = [f"{pb:<12}"]
        for tb in active_times:
            d = cells[(tb, pb)]
            if d["size"] == 0:
                cols.append(f"{'-':>14}")
                continue
            wr = d["wins"] / d["size"]
            avg_p = d["notional"] / d["size"]
            ev = (1 / avg_p) * wr - 1
            cols.append(f"{100*ev:>+9.1f}% n{d['n']:>3}")
        print("".join(cols))

    # Also show win rates separately for the "<0.40" cells in the early windows
    print()
    print("=== Cheap-side trades (price < 0.40) in EARLY windows only ===")
    for tb in ("0-25%", "25-50%"):
        for pb in ("<0.10", "0.10-0.25", "0.25-0.40"):
            d = cells[(tb, pb)]
            if d["size"] == 0:
                continue
            wr = d["wins"] / d["size"]
            avg_p = d["notional"] / d["size"]
            ev = (1 / avg_p) * wr - 1
            print(f"  time={tb:<8} price={pb:<10} n={d['n']:>5} size={d['size']:>9,.0f} "
                  f"avg_p={avg_p:.3f} win={100*wr:.1f}% EV/$={100*ev:+.2f}%")


if __name__ == "__main__":
    main()
