"""
True P&L diagnostic.

For each shadow_exits row on a given UTC date, compute the *actual* outcome
using chainlink prices at window_start vs window_end, and report:
  - bot's true P&L assuming on-chain $0/$1 redemption
  - inverse-fade true P&L same way
  - reported naive inverse P&L (from shadow_exits.csv)
  - misclassification breakdown (bot_won_settled_zero is the key bucket:
    correct predictions reported as losses because winning side had no bid).

Usage:  python scripts/true_pnl.py --date YYYY-MM-DD
        python scripts/true_pnl.py --all   # every date with both files
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

LOG_DIR = "logs"
SHADOW_EXITS_PATH = os.path.join(LOG_DIR, "shadow_exits.csv")


def _load_prices(date_str: str
                 ) -> Dict[str, List[Tuple[float, float]]]:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    path = os.path.join(LOG_DIR,
                        f"chainlink_prices_{dt.strftime('%Y%m%d')}.csv")
    if not os.path.isfile(path):
        return {}
    out: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            out[r["symbol"]].append(
                (float(r["ts_epoch"]), float(r["price"]))
            )
    for v in out.values():
        v.sort()
    return out


def _price_at(arr: List[Tuple[float, float]],
              ts: float) -> Optional[Tuple[float, float]]:
    best = None
    for t, p in arr:
        if t <= ts:
            best = (t, p)
        else:
            break
    return best


def report(date_str: str) -> dict:
    prices = _load_prices(date_str)
    target = datetime.strptime(date_str, "%Y-%m-%d").date()

    rows: List[dict] = []
    with open(SHADOW_EXITS_PATH, newline="") as f:
        for r in csv.DictReader(f):
            try:
                d = datetime.fromisoformat(
                    r["ts_iso"].replace("Z", "+00:00")
                ).astimezone(timezone.utc).date()
            except Exception:
                continue
            if d == target:
                rows.append(r)

    counts: Dict[str, int] = defaultdict(int)
    naive_reported = 0.0
    true_inv = 0.0
    true_bot = 0.0
    n_priced = 0

    for r in rows:
        sym = r["symbol"]
        we = int(float(r["window_end_ts"]))
        ws = we - 900
        arr = prices.get(sym, [])
        # Use first chainlink tick AT or AFTER window_start as the
        # window-open price (Polymarket settles by comparing first tick of
        # window to first tick of next window — both as oracle reads).
        p_start = _price_at(arr, ws + 5)
        p_end = _price_at(arr, we)
        if not p_start or not p_end:
            counts["no_price"] += 1
            continue
        n_priced += 1
        actual_up_won = p_end[1] > p_start[1]
        side = r["side"]
        bot_won = (
            (side == "UP" and actual_up_won)
            or (side == "DOWN" and not actual_up_won)
        )
        sold = r["exit_type"] == "EXPIRY_BID"
        entry = float(r["entry_price"])
        try:
            naive_reported += float(r["inverse_pnl_naive"])
        except (KeyError, ValueError):
            pass
        true_bot += (1.0 if bot_won else 0.0) - entry
        true_inv += (1.0 if not bot_won else 0.0) - (1.0 - entry)
        key = (
            ("bot_won_" if bot_won else "bot_lost_")
            + ("sold" if sold else "settled_zero")
        )
        counts[key] += 1

    return {
        "date": date_str,
        "n_total": len(rows),
        "n_priced": n_priced,
        "counts": dict(counts),
        "naive_reported": naive_reported,
        "true_inverse": true_inv,
        "true_bot": true_bot,
    }


def _print(rep: dict) -> None:
    print(f"\n=== {rep['date']}  (n={rep['n_total']}, priced={rep['n_priced']}) ===")
    for k in sorted(rep["counts"]):
        print(f"  {k:30s} {rep['counts'][k]}")
    print(f"  reported naive inverse:   {rep['naive_reported']:+8.2f}")
    print(f"  TRUE inverse (redeem):    {rep['true_inverse']:+8.2f}")
    print(f"  TRUE bot     (redeem):    {rep['true_bot']:+8.2f}")


def _all_dates() -> List[str]:
    out = set()
    for p in glob.glob(os.path.join(LOG_DIR, "chainlink_prices_*.csv")):
        m = re.search(r"chainlink_prices_(\d{8})\.csv$", p)
        if m:
            d = datetime.strptime(m.group(1), "%Y%m%d")
            out.add(d.strftime("%Y-%m-%d"))
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD UTC")
    ap.add_argument("--all", action="store_true",
                    help="every date with chainlink + shadow data")
    args = ap.parse_args()

    if not args.date and not args.all:
        ap.error("--date or --all required")

    dates = _all_dates() if args.all else [args.date]
    totals = {"naive_reported": 0.0, "true_inverse": 0.0, "true_bot": 0.0,
              "n_total": 0, "n_priced": 0}
    bucket_totals: Dict[str, int] = defaultdict(int)
    for d in dates:
        rep = report(d)
        _print(rep)
        for k, v in rep["counts"].items():
            bucket_totals[k] += v
        for k in ("naive_reported", "true_inverse", "true_bot",
                  "n_total", "n_priced"):
            totals[k] += rep[k]

    if len(dates) > 1:
        print(f"\n=== TOTAL across {len(dates)} dates ===")
        for k in sorted(bucket_totals):
            print(f"  {k:30s} {bucket_totals[k]}")
        print(f"  n_total={totals['n_total']}  "
              f"n_priced={totals['n_priced']}")
        print(f"  reported naive inverse:   {totals['naive_reported']:+8.2f}")
        print(f"  TRUE inverse (redeem):    {totals['true_inverse']:+8.2f}")
        print(f"  TRUE bot     (redeem):    {totals['true_bot']:+8.2f}")


if __name__ == "__main__":
    main()
