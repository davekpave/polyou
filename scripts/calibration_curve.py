"""
Market calibration + earlier-entry research.

Core question: if we bought YES of the eventual-winner side earlier in the
15-min window (at lower YES_ask), would WR survive enough to be profitable?

We measure two things per UTC date:

  (1) MARKET CALIBRATION CURVE.
      For each threshold p in [0.50, 0.55, ..., 0.95], simulate: buy YES
      the first time YES_ask >= p in any 15-min window. Outcome = 1 if YES
      side actually won per chainlink. Aggregate WR per bin.
      Interpretation:
        - WR(p) ~= p   => market is calibrated; entering earlier just trades
                          win-rate for entry cost 1:1; NO net edge.
        - WR(p) >  p   => market under-reacts; earlier entries have +EV.
        - WR(p) <  p   => market over-reacts; later entries (or fade) have +EV.

  (2) EARLIER-ENTRY CURVE FOR BOT SIGNAL.
      Restrict to windows the bot actually traded (from shadow_exits.csv).
      For each, compute the earliest tick where the predicted-side YES_ask
      was within the bin's range. Bin by that early YES_ask and report:
      n_signals, hit_rate, EV/trade = hit_rate*(1-p) - (1-hit_rate)*p.

Both use only existing CSVs — no bot changes.

Usage:
    python scripts/calibration_curve.py --date 2026-05-06
    python scripts/calibration_curve.py --all
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
WINDOW_SECONDS = 15 * 60

BINS: List[Tuple[float, float]] = [
    (0.50, 0.55),
    (0.55, 0.60),
    (0.60, 0.65),
    (0.65, 0.70),
    (0.70, 0.75),
    (0.75, 0.80),
    (0.80, 0.85),
    (0.85, 0.90),
    (0.90, 0.95),
    (0.95, 1.00),
]


# ---------- loaders ----------

def _date_paths(date_str: str) -> Tuple[str, str]:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    book = os.path.join(LOG_DIR,
                        f"book_snapshots_{dt.strftime('%Y%m%d')}.csv")
    chain = os.path.join(LOG_DIR,
                         f"chainlink_prices_{dt.strftime('%Y%m%d')}.csv")
    return book, chain


def _load_chainlink(path: str) -> Dict[str, List[Tuple[float, float]]]:
    out: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    if not os.path.isfile(path):
        return out
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            out[r["symbol"]].append(
                (float(r["ts_epoch"]), float(r["price"]))
            )
    for v in out.values():
        v.sort()
    return out


def _price_at(arr: List[Tuple[float, float]],
              ts: float) -> Optional[float]:
    best = None
    for t, p in arr:
        if t <= ts:
            best = p
        else:
            break
    return best


def _load_book(path: str
               ) -> Dict[Tuple[str, int, str], List[Tuple[float, float]]]:
    """(symbol, window_start_ts, side) -> list of (ts_epoch, best_ask)."""
    out: Dict[Tuple[str, int, str], List[Tuple[float, float]]] = defaultdict(list)
    if not os.path.isfile(path):
        return out
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            ask = r.get("best_ask", "")
            if ask in ("", None):
                continue
            try:
                a = float(ask)
            except ValueError:
                continue
            out[(r["symbol"], int(r["window_start_ts"]), r["side"])].append(
                (float(r["ts_epoch"]), a)
            )
    for v in out.values():
        v.sort()
    return out


# ---------- (1) market calibration ----------

def market_calibration(book, chain) -> Dict[Tuple[float, float], dict]:
    """
    For each (symbol, window_start_ts) with both YES book + chainlink prices:
      - determine winning side via chainlink (price[end] > price[start])
      - compute the first tick where YES_ask crossed each bin
      - record WR for "bought YES at that bin"

    Symmetric for NO bin (since NO_ask = 1 - YES_bid roughly; we use the NO
    leg's own ask ticks where present).
    """
    bin_stats: Dict[Tuple[float, float], dict] = {
        b: {"n": 0, "wins": 0, "n_no": 0, "wins_no": 0} for b in BINS
    }

    # Group by (symbol, window_start_ts)
    keys = {(sym, ws) for (sym, ws, side) in book.keys()}
    for sym, ws in keys:
        we = ws + WINDOW_SECONDS
        arr = chain.get(sym, [])
        p_start = _price_at(arr, ws + 5)
        p_end = _price_at(arr, we)
        if p_start is None or p_end is None:
            continue
        up_won = p_end > p_start  # equivalent to YES winning

        yes_ticks = book.get((sym, ws, "YES"), [])
        no_ticks = book.get((sym, ws, "NO"), [])

        # YES leg: first crossing of each bin lower bound (ascending entry)
        # We want: "earliest moment YES_ask was within [lo, hi)"
        for lo, hi in BINS:
            crossing = next(
                ((t, a) for t, a in yes_ticks
                 if lo <= a < hi and t < we), None
            )
            if crossing is not None:
                bin_stats[(lo, hi)]["n"] += 1
                if up_won:
                    bin_stats[(lo, hi)]["wins"] += 1
            crossing_no = next(
                ((t, a) for t, a in no_ticks
                 if lo <= a < hi and t < we), None
            )
            if crossing_no is not None:
                bin_stats[(lo, hi)]["n_no"] += 1
                if not up_won:
                    bin_stats[(lo, hi)]["wins_no"] += 1
    return bin_stats


# ---------- (2) bot signal earlier-entry ----------

def bot_signal_earlier(date_str: str, book, chain
                       ) -> Dict[Tuple[float, float], dict]:
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    rows: List[dict] = []
    if not os.path.isfile(SHADOW_EXITS_PATH):
        return {}
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

    bin_stats = {b: {"n": 0, "wins": 0} for b in BINS}
    for r in rows:
        sym = r["symbol"]
        we = int(float(r["window_end_ts"]))
        ws = we - WINDOW_SECONDS
        side = r["side"]  # UP / DOWN
        # Predicted-side leg in tracker = YES if UP, NO if DOWN
        pred_leg = "YES" if side == "UP" else "NO"
        ticks = book.get((sym, ws, pred_leg), [])
        if not ticks:
            continue
        arr = chain.get(sym, [])
        p_start = _price_at(arr, ws + 5)
        p_end = _price_at(arr, we)
        if p_start is None or p_end is None:
            continue
        up_won = p_end > p_start
        bot_won = (side == "UP" and up_won) or (side == "DOWN" and not up_won)

        # For each bin, find earliest predicted-side ask in [lo, hi)
        # AFTER the bot's MIN_SIGNAL_AGE_MIN=5min gate would mature.
        # This is the realistically capturable entry under the current
        # signal-age policy; the only thing blocking is MIN_ENTRY_PRICE.
        min_entry_ts = ws + 5 * 60  # MIN_SIGNAL_AGE_MIN gate
        for lo, hi in BINS:
            t = next(((t, a) for t, a in ticks
                      if lo <= a < hi and t >= min_entry_ts), None)
            if t is not None:
                bin_stats[(lo, hi)]["n"] += 1
                if bot_won:
                    bin_stats[(lo, hi)]["wins"] += 1
    return bin_stats


# ---------- reporting ----------

def _print_calibration(stats: Dict[Tuple[float, float], dict]) -> None:
    print("\n  MARKET CALIBRATION (buy YES first time ask in [lo, hi)):")
    print("    bin              YES n   YES WR   YES EV    NO n   NO WR   NO EV")
    for lo, hi in BINS:
        s = stats[(lo, hi)]
        mid = (lo + hi) / 2.0
        if s["n"]:
            wr = s["wins"] / s["n"]
            ev = wr * (1.0 - mid) - (1.0 - wr) * mid
            yes_str = f"{s['n']:5d}   {wr:5.1%}   {ev:+6.3f}"
        else:
            yes_str = f"{0:5d}   {'--':>5s}   {'--':>6s}"
        if s["n_no"]:
            wrn = s["wins_no"] / s["n_no"]
            evn = wrn * (1.0 - mid) - (1.0 - wrn) * mid
            no_str = f"{s['n_no']:5d}   {wrn:5.1%}   {evn:+6.3f}"
        else:
            no_str = f"{0:5d}   {'--':>5s}   {'--':>6s}"
        print(f"    [{lo:.2f},{hi:.2f})  {yes_str}  {no_str}")


def _print_bot(stats: Dict[Tuple[float, float], dict]) -> None:
    if not stats:
        return
    print("\n  BOT SIGNAL EARLIER-ENTRY (predicted leg ask in [lo, hi)):")
    print("    bin               n     WR     EV")
    for lo, hi in BINS:
        s = stats[(lo, hi)]
        mid = (lo + hi) / 2.0
        if not s["n"]:
            continue
        wr = s["wins"] / s["n"]
        ev = wr * (1.0 - mid) - (1.0 - wr) * mid
        print(f"    [{lo:.2f},{hi:.2f})   {s['n']:4d}  {wr:5.1%}  {ev:+6.3f}")


def _all_dates() -> List[str]:
    out = set()
    for p in glob.glob(os.path.join(LOG_DIR, "book_snapshots_*.csv")):
        m = re.search(r"book_snapshots_(\d{8})\.csv$", p)
        if m:
            d = datetime.strptime(m.group(1), "%Y%m%d")
            out.add(d.strftime("%Y-%m-%d"))
    return sorted(out)


def _merge(a: dict, b: dict, keys) -> dict:
    out = dict(a)
    for k in keys:
        out[k] = a.get(k, 0) + b.get(k, 0)
    return out


def _aggregate(per_date_stats: List[Dict[Tuple[float, float], dict]]
               ) -> Dict[Tuple[float, float], dict]:
    if not per_date_stats:
        return {}
    keys = list(per_date_stats[0].values())[0].keys()
    out: Dict[Tuple[float, float], dict] = {
        b: {k: 0 for k in keys} for b in BINS
    }
    for stats in per_date_stats:
        for b in BINS:
            s = stats.get(b, {})
            for k in keys:
                out[b][k] += s.get(k, 0)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD UTC")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if not args.date and not args.all:
        ap.error("--date or --all required")

    dates = _all_dates() if args.all else [args.date]
    cal_per: List[Dict[Tuple[float, float], dict]] = []
    bot_per: List[Dict[Tuple[float, float], dict]] = []

    for d in dates:
        book_path, chain_path = _date_paths(d)
        if not os.path.isfile(book_path):
            print(f"\n=== {d}: no book snapshots, skipping ===")
            continue
        book = _load_book(book_path)
        chain = _load_chainlink(chain_path)
        cal = market_calibration(book, chain)
        bot = bot_signal_earlier(d, book, chain)
        print(f"\n=== {d}  (windows={len({(s,w) for (s,w,_) in book.keys()})}) ===")
        _print_calibration(cal)
        _print_bot(bot)
        cal_per.append(cal)
        bot_per.append(bot)

    if len(dates) > 1:
        print(f"\n=== AGGREGATE across {len(dates)} dates ===")
        _print_calibration(_aggregate(cal_per))
        _print_bot(_aggregate(bot_per))


if __name__ == "__main__":
    main()
