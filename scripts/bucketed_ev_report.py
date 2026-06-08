"""Bucketed EV report.

Reads logs/rr_blocks_resolved.csv and bins counterfactual EV by the price
we would have paid (tracker_ask). Also bins by signal_rr percentile.
Sanity-check tool only — do NOT use to retune thresholds without a
walk-forward, OOS run (see walk_forward_threshold.py).

Usage:
    .venv/Scripts/python.exe scripts/bucketed_ev_report.py
    .venv/Scripts/python.exe scripts/bucketed_ev_report.py --by symbol_side
"""
from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

RR_PATH = Path("logs/rr_blocks_resolved.csv")

ASK_BUCKETS = [
    (0.00, 0.50),
    (0.50, 0.60),
    (0.60, 0.70),
    (0.70, 0.80),
    (0.80, 0.85),
    (0.85, 0.90),
    (0.90, 0.95),
    (0.95, 1.01),
]

RR_BUCKETS = [
    (0.00, 0.10),
    (0.10, 0.20),
    (0.20, 0.30),
    (0.30, 0.40),
    (0.40, 0.50),
    (0.50, 0.75),
    (0.75, 1.01),
]


def _bucket(value: float, edges: list[tuple[float, float]]) -> str:
    for lo, hi in edges:
        if lo <= value < hi:
            return f"[{lo:.2f},{hi:.2f})"
    return "n/a"


def _iter_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("would_have_won") not in ("0", "1"):
                continue
            try:
                ev = float(r["payoff_per_dollar"])
                ask = float(r.get("tracker_ask") or "nan")
                rr = float(r.get("signal_rr") or "nan")
            except ValueError:
                continue
            if math.isnan(ev):
                continue
            yield {
                "symbol": r.get("symbol", ""),
                "side": r.get("side", ""),
                "ask": ask,
                "rr": rr,
                "won": int(r["would_have_won"] == "1"),
                "ev": ev,
            }


def _print_table(title: str, rows: dict, key_label: str) -> None:
    print(f"\n--- {title} ---")
    print(f"{key_label:<22} {'n':>7} {'win%':>6} {'EV/$':>9}")
    for k in sorted(rows.keys()):
        v = rows[k]
        if v["n"] == 0:
            continue
        wr = v["w"] / v["n"] * 100
        ev = v["ev"] / v["n"]
        print(f"{str(k):<22} {v['n']:>7} {wr:>5.1f}% {ev:>+9.4f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--by",
        choices=["overall", "symbol_side"],
        default="overall",
        help="Stratification: overall or per (symbol, side).",
    )
    args = parser.parse_args()

    if not RR_PATH.exists():
        print(f"missing {RR_PATH}; run scripts/resolve_decision_outcomes.py first")
        return

    by_ask: dict = defaultdict(lambda: {"n": 0, "w": 0, "ev": 0.0})
    by_rr: dict = defaultdict(lambda: {"n": 0, "w": 0, "ev": 0.0})

    for r in _iter_rows(RR_PATH):
        ask_b = _bucket(r["ask"], ASK_BUCKETS) if not math.isnan(r["ask"]) else "n/a"
        rr_b = _bucket(r["rr"], RR_BUCKETS) if not math.isnan(r["rr"]) else "n/a"
        prefix = "" if args.by == "overall" else f"{r['symbol']}/{r['side']:<3} "
        ka = f"{prefix}{ask_b}"
        kr = f"{prefix}{rr_b}"
        by_ask[ka]["n"] += 1
        by_ask[ka]["w"] += r["won"]
        by_ask[ka]["ev"] += r["ev"]
        by_rr[kr]["n"] += 1
        by_rr[kr]["w"] += r["won"]
        by_rr[kr]["ev"] += r["ev"]

    _print_table("rr_blocks EV by tracker_ask bucket", by_ask, "ask_bucket")
    _print_table("rr_blocks EV by signal_rr bucket", by_rr, "rr_bucket")
    print("\nReminder: counterfactual only. Confirm with walk_forward_threshold.py before tuning.")


if __name__ == "__main__":
    main()
