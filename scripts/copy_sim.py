"""
copy_sim.py

Simulate a follower that copies top-N OOS-validated traders with a fixed delay.
For each leader fill on the test period:
  - At leader_ts + delay, find the next trade on the same token (proxy for what
    a market-taker copier would pay/receive).
  - If a same-side trade exists within max_lookahead, use its price.
  - Else: skip (no fill for copier).
  - Score copier PnL against gamma winner.

Usage:
    python scripts/copy_sim.py [--top 100] [--delay 5] [--max-lookahead 60]
                               [--fee-bps 0] [--clip-tte-min 30]
"""
from __future__ import annotations
import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

CACHE = Path("cache/trades")
META = CACHE / "_meta.csv"
GAMMA_WIN = CACHE / "_meta_gamma_winners.csv"
TOP = Path("logs/oos_top_traders.csv")

SLUG_RE = re.compile(r"^(btc|eth|sol)-updown-15m-(\d+)$")
MARKET_LEN = 900  # 15-minute window


def slug_close_ts(slug: str) -> int | None:
    """Slug timestamp is market OPEN; close = open + 900."""
    m = SLUG_RE.match(slug)
    return int(m.group(2)) + MARKET_LEN if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=100, help="how many top OOS traders to follow")
    ap.add_argument("--delay", type=int, default=5, help="seconds copier lags leader")
    ap.add_argument("--max-lookahead", type=int, default=60,
                    help="max seconds after leader_ts+delay to wait for a trade quote")
    ap.add_argument("--fee-bps", type=float, default=0.0,
                    help="copier round-trip fee in bps of notional (taker fee)")
    ap.add_argument("--clip-tte-min", type=int, default=0,
                    help="ignore leader fills with seconds-to-resolution > clip-tte-min*60+thresh")
    ap.add_argument("--min-tte", type=int, default=10,
                    help="ignore leader fills with seconds-to-resolution < min-tte (no time to copy)")
    ap.add_argument("--train-days", type=int, default=60)
    args = ap.parse_args()

    # Load top traders from OOS file
    if not TOP.exists():
        print(f"Missing {TOP}; run oos_validate.py first.")
        return
    leaders = set()
    for r in list(csv.DictReader(open(TOP, encoding="utf-8")))[: args.top]:
        leaders.add(r["address"].lower())
    print(f"Following {len(leaders)} leaders, delay={args.delay}s, lookahead={args.max_lookahead}s, "
          f"fee_bps={args.fee_bps}, min_tte={args.min_tte}s")

    winners = {r["slug"]: r["gamma_winner"]
               for r in csv.DictReader(open(GAMMA_WIN, encoding="utf-8"))}
    meta = list(csv.DictReader(open(META, encoding="utf-8")))

    close_list = [slug_close_ts(m["slug"]) for m in meta]
    close_list = [t for t in close_list if t]
    t_min = min(close_list)
    split_ts = t_min + int(args.train_days * 86400)

    # Stats
    leader_pnl = 0.0       # the leader's realized pnl on copied fills
    copier_pnl = 0.0       # what the copier would have made
    copier_fees = 0.0
    copier_volume = 0.0
    n_signals = 0
    n_filled = 0
    n_no_quote = 0
    n_too_late = 0
    slip_samples = []

    n_test_mkts = 0
    for m in meta:
        slug = m["slug"]
        winner = winners.get(slug)
        if not winner:
            continue
        close_ts = slug_close_ts(slug)
        if close_ts is None or close_ts < split_ts:
            continue  # train period only used for ranking
        f = CACHE / f"{slug}.json"
        if not (f.exists() and f.stat().st_size > 2):
            continue
        try:
            trades = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        n_test_mkts += 1

        # Trades came back DESC by timestamp; sort ASC
        trades.sort(key=lambda t: int(t.get("timestamp", 0) or 0))

        # Build per-token sorted list of (ts, side, price) for quote lookup
        per_token: dict[str, list[tuple[int, str, float]]] = defaultdict(list)
        for t in trades:
            try:
                ts = int(t.get("timestamp", 0) or 0)
                asset = str(t.get("asset", ""))
                side = t.get("side", "")
                price = float(t.get("price", 0) or 0)
            except Exception:
                continue
            if not asset or price <= 0:
                continue
            per_token[asset].append((ts, side, price))
        for k in per_token:
            per_token[k].sort()

        # Iterate leader fills
        for t in trades:
            try:
                addr = (t.get("proxyWallet") or "").lower()
            except Exception:
                continue
            if addr not in leaders:
                continue
            try:
                ts = int(t.get("timestamp", 0) or 0)
                asset = str(t.get("asset", ""))
                side = t.get("side", "")
                price = float(t.get("price", 0) or 0)
                size = float(t.get("size", 0) or 0)
            except Exception:
                continue
            if size <= 0 or price <= 0 or side not in ("BUY", "SELL"):
                continue
            tte = close_ts - ts
            if tte < args.min_tte:
                # too close to (or after) resolution; copier can't fill in time
                n_too_late += 1
                continue
            if args.clip_tte_min and tte > args.clip_tte_min * 60:
                # too early in market
                continue
            n_signals += 1

            # Leader's own pnl on this fill (per dollar at risk = size*price)
            won = (asset == winner)
            if side == "BUY":
                lp = size * (1.0 - price) if won else -size * price
            else:
                lp = -size * (1.0 - price) if won else size * price
            leader_pnl += lp

            # Find next trade on same token at ts+delay .. ts+delay+lookahead
            quote_lo = ts + args.delay
            quote_hi = quote_lo + args.max_lookahead
            tlist = per_token.get(asset, [])
            # binary search for first ts >= quote_lo
            lo, hi = 0, len(tlist)
            while lo < hi:
                mid = (lo + hi) // 2
                if tlist[mid][0] < quote_lo:
                    lo = mid + 1
                else:
                    hi = mid
            quote_price = None
            for j in range(lo, len(tlist)):
                qts, _qside, qprice = tlist[j]
                if qts > quote_hi:
                    break
                quote_price = qprice
                break
            if quote_price is None:
                n_no_quote += 1
                continue

            # Copier mirrors leader's side on the same token
            n_filled += 1
            cp_price = quote_price
            cash = size * cp_price
            copier_volume += cash
            slip_samples.append(cp_price - price if side == "BUY" else price - cp_price)
            if side == "BUY":
                cp = size * (1.0 - cp_price) if won else -size * cp_price
            else:
                cp = -size * (1.0 - cp_price) if won else size * cp_price
            fee = cash * (args.fee_bps / 1e4)
            copier_fees += fee
            copier_pnl += cp - fee

    print(f"\nTest markets considered: {n_test_mkts}")
    print(f"Leader signals (after min_tte filter): {n_signals}")
    print(f"  filled by copier: {n_filled}  ({n_filled/max(1,n_signals):.1%})")
    print(f"  no quote in window: {n_no_quote}  too late (<min_tte): {n_too_late}")
    print()
    print(f"Leader  PnL on copied fills: {leader_pnl:>14,.2f}")
    print(f"Copier  PnL                : {copier_pnl:>14,.2f}   "
          f"(fees: {copier_fees:>10,.2f})")
    print(f"Copier  volume (notional)  : {copier_volume:>14,.2f}")
    if copier_volume > 0:
        print(f"Copier  EV per $ at risk   : {copier_pnl / copier_volume:.3%}")
    if slip_samples:
        slip_samples.sort()
        print(f"Adverse slippage (price moved against copier, prob units):")
        print(f"  mean={mean(slip_samples):+.4f}  median={median(slip_samples):+.4f}  "
              f"p25={slip_samples[len(slip_samples)//4]:+.4f}  "
              f"p75={slip_samples[3*len(slip_samples)//4]:+.4f}")


if __name__ == "__main__":
    main()
