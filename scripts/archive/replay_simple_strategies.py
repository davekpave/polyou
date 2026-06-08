"""SOL-only honest replay — does the simplest possible strategy beat the
complex per-(sym,side,bucket) proposal?

Rules tested:
  A) trade every SOL (UP+DOWN) resolved row, no caps
  B) trade every SOL with rr_floor only (sp <= 0.95)
  C) for comparison: BTC UP only (the other clean +EV slice)
  D) for comparison: combined SOL + BTC UP
"""
from __future__ import annotations

import csv
from pathlib import Path

INPUT = Path(__file__).resolve().parent.parent / "logs" / "derived" / "block_outcomes.csv"
RR_MIN_FLOOR = 0.05  # never buy at sp > 0.95


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_resolved(label_conf: str) -> bool:
    return label_conf in ("strict", "near_close")


def summarize(name, rows):
    n = len(rows)
    if n == 0:
        return f"  {name:42s}  n=0"
    wins = sum(1 for r in rows if to_float(r["block_won"]) == 1.0)
    payoffs = [to_float(r["payoff_per_dollar"]) or 0.0 for r in rows]
    snaps = [to_float(r["snapshot_price"]) or 0.0 for r in rows]
    total = sum(payoffs)
    mean_sp = sum(snaps) / n
    wr = wins / n
    return (
        f"  {name:42s}  n={n:5d}  win={wr*100:5.1f}%  "
        f"sp̄={mean_sp:.3f}  edge={(wr-mean_sp)*100:+6.2f}pp  "
        f"EV/$={total/n:+.4f}  total=${total:+.2f}"
    )


def main():
    with INPUT.open("r", newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    resolved = [r for r in all_rows if is_resolved(r["outcome_label_conf"])]

    def in_pairs(r, pairs):
        return (r["symbol"], r["side"]) in pairs

    def with_floor(rows):
        return [r for r in rows
                if (sp := to_float(r["snapshot_price"])) is not None
                and sp <= 1.0 - RR_MIN_FLOOR]

    sol_pairs = {("SOLUSD", "UP"), ("SOLUSD", "DOWN")}
    btc_up = {("BTCUSD", "UP")}
    sol_btc_up = sol_pairs | btc_up

    print("=" * 96)
    print("SIMPLE STRATEGY HONEST REPLAY (resolved = strict + clean near_close)")
    print("=" * 96)
    print(summarize("ALL resolved (no filter)", resolved))
    print()
    print("--- SOL only ---")
    sol_all = [r for r in resolved if in_pairs(r, sol_pairs)]
    print(summarize("A) SOL UP+DOWN, no caps", sol_all))
    print(summarize("A) SOL UP+DOWN, rr_floor only (sp<=.95)", with_floor(sol_all)))
    print(summarize("    SOL UP only", [r for r in sol_all if r["side"] == "UP"]))
    print(summarize("    SOL DOWN only", [r for r in sol_all if r["side"] == "DOWN"]))
    print()
    print("--- BTC UP only (the other clean slice) ---")
    btc_up_rows = [r for r in resolved if in_pairs(r, btc_up)]
    print(summarize("C) BTC UP, no caps", btc_up_rows))
    print(summarize("C) BTC UP, rr_floor only", with_floor(btc_up_rows)))
    print(summarize("C) BTC UP, sp in [0.80, 0.95]",
                    [r for r in btc_up_rows
                     if (sp := to_float(r["snapshot_price"])) is not None
                     and 0.80 <= sp <= 0.95]))
    print()
    print("--- Combined SOL + BTC UP (the 'clean +EV everywhere' set) ---")
    combo = [r for r in resolved if in_pairs(r, sol_btc_up)]
    print(summarize("D) SOL+BTC_UP, no caps", combo))
    print(summarize("D) SOL+BTC_UP, rr_floor only", with_floor(combo)))
    print()
    print("--- Reference: PROPOSAL (full per-(sym,side) caps) ---")
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

    def proposal_passes(r):
        sp = to_float(r["snapshot_price"])
        if sp is None:
            return False
        cap = SIDE_PRICE_CAP.get((r["symbol"], r["side"]))
        if cap is None or sp > 1.0 - RR_MIN_FLOOR:
            return False
        return sp <= cap

    print(summarize("PROPOSAL (per-pair caps + rr_floor)",
                    [r for r in resolved if proposal_passes(r)]))


if __name__ == "__main__":
    main()
