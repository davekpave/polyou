"""Audit realized PnL for the CURRENT bot only (hold-to-expiry era).

Cutover: bot switched to hold-to-expiry on/around 2026-04-24. Filter by
the EXPIRY_SELL exit type and any timestamp >= 2026-04-24 00:00 UTC.

Reads:
  - logs/exit_log.csv  (schema: timestamp,token_id,type,entry_price,exit_price,profit_cents)

Dedup: first row per token_id (canonical exit).
"""
from __future__ import annotations

import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
EXIT_LOG = ROOT / "logs" / "exit_log.csv"

CUTOVER_TS = dt.datetime(2026, 4, 24, 0, 0, 0, tzinfo=dt.timezone.utc).timestamp()


def load_canonical():
    rows = list(csv.DictReader(EXIT_LOG.open(encoding="utf-8")))
    seen = set()
    canon = []
    for r in rows:
        tid = r.get("token_id")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        canon.append(r)
    return canon, len(rows)


def fnum(x):
    try:
        return float(x)
    except Exception:
        return None


def main():
    canon, total_rows = load_canonical()
    current = [
        r for r in canon
        if (fnum(r.get("timestamp")) or 0) >= CUTOVER_TS
        and r.get("type") in ("EXPIRY_SELL", "SETTLED_ZERO")
    ]

    by_type = defaultdict(list)
    for r in current:
        by_type[r.get("type", "")].append(r)

    print(f"exit_log.csv : raw rows={total_rows} canonical={len(canon)}")
    print(f"cutover (UTC): {dt.datetime.utcfromtimestamp(CUTOVER_TS):%Y-%m-%d %H:%M:%S}")
    print(f"current-era closures (>= cutover): {len(current)}")
    print()

    if not current:
        print("No current-era trades.")
        return

    timestamps = [fnum(r["timestamp"]) for r in current]
    t_min = min(timestamps); t_max = max(timestamps)
    span_days = (t_max - t_min) / 86400.0
    print(f"date range: {dt.datetime.utcfromtimestamp(t_min):%Y-%m-%d %H:%M} UTC")
    print(f"         -> {dt.datetime.utcfromtimestamp(t_max):%Y-%m-%d %H:%M} UTC")
    print(f"         span: {span_days:.2f} days")
    print()

    print("by exit type:")
    for t, rows in sorted(by_type.items()):
        n = len(rows)
        profits = [fnum(r["profit_cents"]) or 0.0 for r in rows]
        wins = sum(1 for p in profits if p > 0)
        losses = sum(1 for p in profits if p < 0)
        flats = n - wins - losses
        total = sum(profits)
        ev_per_dollar = mean(profits) if profits else 0.0  # entry/exit are per-share fractions; profit_cents already dollars-per-share
        print(f"  {t:14s} n={n:3d}  wins={wins} losses={losses} flat={flats}")
        print(f"    total ${total:+.2f}   mean per trade ${ev_per_dollar:+.3f}")

    # Headline aggregate
    profits = [fnum(r["profit_cents"]) or 0.0 for r in current]
    n = len(profits)
    total = sum(profits)
    wins = sum(1 for p in profits if p > 0)
    print()
    print("=" * 60)
    print("CURRENT BOT HEADLINE (hold-to-expiry)")
    print("=" * 60)
    print(f"  closures      : {n}")
    print(f"  span          : {span_days:.2f} days")
    print(f"  total realized: ${total:+.2f}")
    print(f"  per-trade EV  : ${total / n:+.3f}")
    print(f"  win rate      : {wins}/{n} = {wins / n * 100:.1f}%")
    print(f"  trades/day    : {n / span_days:.2f}" if span_days > 0 else "")

    # Distribution of profits
    print()
    print("profit distribution (per-share dollars):")
    profits_sorted = sorted(profits)
    for q_label, q in [("min", 0.0), ("p25", 0.25), ("median", 0.5), ("p75", 0.75), ("max", 1.0)]:
        if q == 0.0:
            v = profits_sorted[0]
        elif q == 1.0:
            v = profits_sorted[-1]
        else:
            i = int(q * (len(profits_sorted) - 1))
            v = profits_sorted[i]
        print(f"  {q_label:6s} ${v:+.3f}")

    # List every trade for transparency
    print()
    print("every current-era exit:")
    print(f"  {'when (UTC)':20s} {'type':14s} {'entry':>6s} {'exit':>6s} {'pnl':>7s}  token...")
    for r in sorted(current, key=lambda r: fnum(r["timestamp"]) or 0):
        ts = fnum(r["timestamp"]) or 0
        when = dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        e = fnum(r.get("entry_price"))
        x = fnum(r.get("exit_price"))
        p = fnum(r.get("profit_cents")) or 0.0
        e_s = f"{e:.3f}" if e is not None else "  -  "
        x_s = f"{x:.3f}" if x is not None else "  -  "
        tid = r.get("token_id", "")
        print(f"  {when:20s} {r.get('type',''):14s} {e_s:>6s} {x_s:>6s} ${p:+6.3f}  {tid[:12]}...")


if __name__ == "__main__":
    main()
