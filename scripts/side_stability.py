"""
Side-stability check for the bot's directional signal.

The bot picks side via: UP if chainlink_price(now) > anchor_price else DOWN
(anchor = chainlink at window_start). The signal can flip if price wobbles
across the anchor.

For each historical bot trade, this checks: at earlier moments in the same
window, did the simple side rule produce the SAME side the bot eventually
entered on? If yes most of the time, lowering MIN_ENTRY_PRICE is safe — we
would have correctly entered the same direction earlier. If no, the +EV
forecast is overstated because we'd be entering on a pick that the bot
itself would have later abandoned.

Output two views:
  (1) "stable from t" - fraction of trades whose side-rule matches entry
      side from a given offset onward, continuously.
  (2) "matches at t" - fraction whose side-rule at exactly offset t matches.

Usage:
    python scripts/side_stability.py
"""

from __future__ import annotations

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

# Probe these offsets from window_start (seconds).
OFFSETS = [60, 120, 180, 240, 300, 360, 420, 480, 540, 600, 660, 720]


def _load_chainlink_for_dates(dates: List[str]
                              ) -> Dict[str, List[Tuple[float, float]]]:
    out: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for d in dates:
        dt = datetime.strptime(d, "%Y-%m-%d")
        path = os.path.join(LOG_DIR,
                            f"chainlink_prices_{dt.strftime('%Y%m%d')}.csv")
        if not os.path.isfile(path):
            continue
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


def main() -> None:
    if not os.path.isfile(SHADOW_EXITS_PATH):
        print("No shadow_exits.csv")
        return

    # Discover dates from chainlink files
    dates = sorted({
        re.search(r"chainlink_prices_(\d{8})\.csv$", p).group(1)
        for p in glob.glob(os.path.join(LOG_DIR, "chainlink_prices_*.csv"))
    })
    dates_iso = [datetime.strptime(d, "%Y%m%d").strftime("%Y-%m-%d")
                 for d in dates]
    chain = _load_chainlink_for_dates(dates_iso)

    # Load shadow_exits and filter to dates we have chainlink for
    rows: List[dict] = []
    valid_dates = set(dates_iso)
    with open(SHADOW_EXITS_PATH, newline="") as f:
        for r in csv.DictReader(f):
            try:
                d = datetime.fromisoformat(
                    r["ts_iso"].replace("Z", "+00:00")
                ).astimezone(timezone.utc).date().isoformat()
            except Exception:
                continue
            if d in valid_dates:
                rows.append(r)

    # Per-trade: anchor + entry_side; record side at each offset
    # offset_match[off] = (matches, n)
    offset_match: Dict[int, Tuple[int, int]] = {o: (0, 0) for o in OFFSETS}
    # stable_from[off] = (n trades whose side at every probe in [off..end] matches entry, n)
    stable_from: Dict[int, Tuple[int, int]] = {o: (0, 0) for o in OFFSETS}

    n_eligible = 0
    n_skipped_no_anchor = 0

    for r in rows:
        sym = r["symbol"]
        we = int(float(r["window_end_ts"]))
        ws = we - WINDOW_SECONDS
        entry_side = r["side"]
        arr = chain.get(sym, [])
        anchor = _price_at(arr, ws + 5)
        if anchor is None:
            n_skipped_no_anchor += 1
            continue
        n_eligible += 1

        # Compute side at each offset
        side_at: Dict[int, Optional[str]] = {}
        for off in OFFSETS:
            t = ws + off
            if t >= we:
                side_at[off] = None
                continue
            p = _price_at(arr, t)
            if p is None or p == anchor:
                side_at[off] = None
                continue
            side_at[off] = "UP" if p > anchor else "DOWN"

        for off in OFFSETS:
            s = side_at[off]
            if s is None:
                continue
            m, n = offset_match[off]
            offset_match[off] = (m + (1 if s == entry_side else 0), n + 1)

        # stable_from: continuously match from off through end
        for off in OFFSETS:
            tail = [side_at[o] for o in OFFSETS if o >= off]
            tail_present = [s for s in tail if s is not None]
            if not tail_present:
                continue
            m, n = stable_from[off]
            ok = all(s == entry_side for s in tail_present)
            stable_from[off] = (m + (1 if ok else 0), n + 1)

    print(f"Trades analyzed: {n_eligible}  (skipped no-anchor: {n_skipped_no_anchor})")
    print()
    print("Match-at-offset:  fraction of trades whose simple-rule side at "
          "exactly t=ws+offset matches the bot's entry side")
    print(f"  {'offset':>8s}  {'n':>5s}  {'match%':>8s}")
    for off in OFFSETS:
        m, n = offset_match[off]
        if n:
            print(f"  {off:>8d}  {n:>5d}  {m/n:>8.1%}")

    print()
    print("Stable-from-offset: fraction whose simple-rule side matches entry "
          "side at ALL probes from t=ws+offset to window_end (continuously)")
    print(f"  {'offset':>8s}  {'n':>5s}  {'stable%':>8s}")
    for off in OFFSETS:
        m, n = stable_from[off]
        if n:
            print(f"  {off:>8d}  {n:>5d}  {m/n:>8.1%}")


if __name__ == "__main__":
    main()
