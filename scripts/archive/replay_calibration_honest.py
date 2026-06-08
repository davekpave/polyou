"""HONEST replay of CALIBRATION_PROPOSAL — uses ALL resolved outcomes,
not just strict-labeled. Drops only 'broken' (yes_no_disagree) rows.

This is what the bot would actually see live: every outcome counts."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

INPUT = Path(__file__).resolve().parent.parent / "logs" / "derived" / "block_outcomes.csv"

SIDE_PRICE_CAP = {
    ("BTCUSD", "UP"):   0.92,
    ("BTCUSD", "DOWN"): 0.85,
    ("ETHUSD", "UP"):   0.85,
    ("ETHUSD", "DOWN"): 0.80,
    ("SOLUSD", "UP"):   0.95,
    ("SOLUSD", "DOWN"): 0.92,
    ("XRPUSD", "UP"):   0.97,
    ("XRPUSD", "DOWN"): 0.92,
}
RR_MIN_FLOOR = 0.05


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_resolved(label_conf: str) -> bool:
    """Include strict + near_close (clean). Drop yes_no_disagree (broken markets)
    and stale_terminal/indeterminate (we don't actually know the outcome)."""
    if label_conf == "strict":
        return True
    if label_conf == "near_close":  # clean near-close, no _yes_no_disagree
        return True
    return False


def passes(row) -> bool:
    sp = to_float(row["snapshot_price"])
    if sp is None:
        return False
    cap = SIDE_PRICE_CAP.get((row["symbol"], row["side"]))
    if cap is None:
        return False
    if sp > 1.0 - RR_MIN_FLOOR:
        return False
    return sp <= cap


def summarize(name, rows):
    n = len(rows)
    if n == 0:
        return f"  {name:38s}  n=0"
    wins = sum(1 for r in rows if to_float(r["block_won"]) == 1.0)
    payoffs = [to_float(r["payoff_per_dollar"]) or 0.0 for r in rows]
    snaps = [to_float(r["snapshot_price"]) or 0.0 for r in rows]
    total = sum(payoffs)
    mean_sp = sum(snaps) / n
    wr = wins / n
    return (
        f"  {name:38s}  n={n:5d}  win={wr*100:5.1f}%  "
        f"sp̄={mean_sp:.3f}  edge={(wr-mean_sp)*100:+6.2f}pp  "
        f"EV/$={total/n:+.4f}  total=${total:+.2f}"
    )


def main():
    with INPUT.open("r", newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    resolved = [r for r in all_rows if is_resolved(r["outcome_label_conf"])]
    print(f"Total rows                      : {len(all_rows)}")
    print(f"Resolved (strict + near_close)  : {len(resolved)}")
    print(f"Strict only                     : {sum(1 for r in resolved if r['outcome_label_conf']=='strict')}")
    print(f"Near_close (clean)              : {sum(1 for r in resolved if r['outcome_label_conf']=='near_close')}")
    print()

    print("=" * 88)
    print("HONEST REPLAY (resolved=strict+near_close, no label cherry-picking)")
    print("=" * 88)

    proposal_trades = [r for r in resolved if passes(r)]
    print(summarize("BASELINE: trade-everything resolved", resolved))
    print(summarize("PROPOSAL: caps + rr_floor", proposal_trades))
    print()

    print("PROPOSAL — by (symbol, side):")
    keys = sorted({(r["symbol"], r["side"]) for r in proposal_trades})
    for sym, side in keys:
        sub = [r for r in proposal_trades if r["symbol"] == sym and r["side"] == side]
        cap = SIDE_PRICE_CAP[(sym, side)]
        print(summarize(f"{sym} {side} (cap={cap})", sub))
    print()

    # Full-population edge per (symbol, side)
    print("BASELINE per (symbol, side), no caps:")
    for sym, side in sorted({(r["symbol"], r["side"]) for r in resolved}):
        sub = [r for r in resolved if r["symbol"] == sym and r["side"] == side]
        print(summarize(f"{sym} {side}", sub))
    print()

    # Per-bucket edge (the real picture per-bucket)
    print("FULL-POPULATION edge per sp-bucket per (symbol, side) — what bot sees live:")
    print(f"  {'pair':12s}  {'bucket':12s}  {'n':>5s}  {'win%':>6s}  {'sp̄':>6s}  {'edge':>7s}  {'EV/$':>8s}")
    buckets = [(0.70, 0.80, "0.70-0.80"), (0.80, 0.85, "0.80-0.85"),
               (0.85, 0.90, "0.85-0.90"), (0.90, 0.95, "0.90-0.95"),
               (0.95, 1.01, "0.95-1.00")]
    for sym, side in sorted({(r["symbol"], r["side"]) for r in resolved}):
        sub = [r for r in resolved if r["symbol"] == sym and r["side"] == side]
        for lo, hi, name in buckets:
            bucket_rows = [r for r in sub
                           if to_float(r["snapshot_price"]) is not None
                           and lo <= float(r["snapshot_price"]) < hi]
            n = len(bucket_rows)
            if n < 20:
                continue
            wins = sum(1 for r in bucket_rows if to_float(r["block_won"]) == 1.0)
            payoffs = [to_float(r["payoff_per_dollar"]) or 0.0 for r in bucket_rows]
            snaps = [to_float(r["snapshot_price"]) or 0.0 for r in bucket_rows]
            mean_sp = sum(snaps) / n
            wr = wins / n
            ev = sum(payoffs) / n
            edge_pp = (wr - mean_sp) * 100
            marker = " 🟢" if ev > 0 else " 🔴" if ev < -0.02 else ""
            print(f"  {sym} {side:4s}  {name:12s}  {n:5d}  {wr*100:5.1f}%  {mean_sp:.3f}  {edge_pp:+6.2f}pp  {ev:+7.4f}{marker}")


if __name__ == "__main__":
    main()
