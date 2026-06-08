"""Phase A — Option 1: Replay-only harness.

Applies the SIDE_PRICE_CAP rule from CALIBRATION_PROPOSAL.md against the
labeled blocked-trade dataset (logs/derived/block_outcomes.csv) and reports
counterfactual P&L, win rate, and EV/$1 per slice.

Read-only. Does not touch the bot or any live state. Uses payoff_per_dollar
already present in the CSV (= 1-snapshot_price on win, -snapshot_price on loss).

Usage:
    .venv/Scripts/python.exe scripts/replay_calibration_proposal.py
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

INPUT = Path(__file__).resolve().parent.parent / "logs" / "derived" / "block_outcomes.csv"

# Proposed rules (from CALIBRATION_PROPOSAL.md §3.1)
SIDE_PRICE_CAP = {
    ("BTCUSD", "UP"):   0.92,
    ("BTCUSD", "DOWN"): 0.85,
    ("ETHUSD", "UP"):   0.85,   # no historical data — bootstrap
    ("ETHUSD", "DOWN"): 0.80,   # no historical data — bootstrap
    ("SOLUSD", "UP"):   0.95,
    ("SOLUSD", "DOWN"): 0.92,
    ("XRPUSD", "UP"):   0.97,
    ("XRPUSD", "DOWN"): 0.92,
}

# Universal sanity floor (block trivially-priced markets)
RR_MIN_FLOOR = 0.05  # equivalent to snapshot_price <= ~0.952


def load_rows(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_float(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def passes_proposal(row: dict) -> tuple[bool, str]:
    """Return (would_trade, reason_if_blocked)."""
    sym = row["symbol"]
    side = row["side"]
    sp = to_float(row["snapshot_price"])
    if sp is None:
        return False, "no_snapshot_price"
    cap = SIDE_PRICE_CAP.get((sym, side))
    if cap is None:
        return False, f"unknown_pair_{sym}_{side}"
    # Universal floor: block if snapshot >= 1 - RR_MIN_FLOOR
    if sp > 1.0 - RR_MIN_FLOOR:
        return False, "rr_floor"
    if sp > cap:
        return False, "side_price_cap"
    return True, ""


def summarize(name: str, rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"name": name, "n": 0}
    wins = sum(1 for r in rows if to_float(r["block_won"]) == 1.0)
    payoffs = [to_float(r["payoff_per_dollar"]) or 0.0 for r in rows]
    snaps = [to_float(r["snapshot_price"]) or 0.0 for r in rows]
    total_pnl = sum(payoffs)
    mean_sp = sum(snaps) / n
    win_rate = wins / n
    ev_per_dollar = total_pnl / n
    breakeven = mean_sp  # need win_rate > sp on average to be +EV
    edge_pp = (win_rate - mean_sp) * 100
    return {
        "name": name,
        "n": n,
        "wins": wins,
        "win_rate": win_rate,
        "mean_sp": mean_sp,
        "edge_pp": edge_pp,
        "ev_per_dollar": ev_per_dollar,
        "total_pnl_per_dollar_staked": total_pnl,
    }


def fmt(s: dict) -> str:
    if s["n"] == 0:
        return f"  {s['name']:35s}  n=0"
    return (
        f"  {s['name']:35s}  n={s['n']:5d}  win={s['win_rate']*100:5.1f}%  "
        f"sp̄={s['mean_sp']:.3f}  edge={s['edge_pp']:+6.2f}pp  "
        f"EV/$={s['ev_per_dollar']:+.4f}  total=${s['total_pnl_per_dollar_staked']:+.2f}"
    )


def main() -> int:
    if not INPUT.exists():
        print(f"ERROR: {INPUT} not found", file=sys.stderr)
        return 1

    all_rows = load_rows(INPUT)
    strict = [r for r in all_rows if r.get("outcome_label_conf") == "strict"]

    print(f"Loaded {len(all_rows)} rows from {INPUT.name}")
    print(f"Strict-resolved subset: {len(strict)} rows\n")

    # Apply proposal
    would_trade: list[dict] = []
    blocked_by_reason: dict[str, int] = defaultdict(int)
    for r in strict:
        ok, reason = passes_proposal(r)
        if ok:
            would_trade.append(r)
        else:
            blocked_by_reason[reason] += 1

    print("=" * 78)
    print("PROPOSAL REPLAY (strict-resolved blocks only)")
    print("=" * 78)
    print(f"Total strict blocks         : {len(strict)}")
    print(f"Would trade under proposal  : {len(would_trade)} ({len(would_trade)/len(strict)*100:.1f}%)")
    print(f"Blocked by proposal         : {len(strict)-len(would_trade)}")
    for reason, n in sorted(blocked_by_reason.items(), key=lambda kv: -kv[1]):
        print(f"    {reason:20s}  {n}")
    print()

    # Overall headline
    overall = summarize("PROPOSAL: would-trade (overall)", would_trade)
    baseline = summarize("BASELINE: trade-everything strict", strict)
    print("HEADLINE")
    print(fmt(baseline))
    print(fmt(overall))
    print()

    # Per-symbol, per-side breakdown of would-trade set
    print("PROPOSAL — by (symbol, side):")
    keys = sorted({(r["symbol"], r["side"]) for r in would_trade})
    for sym, side in keys:
        slice_rows = [r for r in would_trade if r["symbol"] == sym and r["side"] == side]
        cap = SIDE_PRICE_CAP.get((sym, side))
        print(fmt(summarize(f"{sym} {side} (cap={cap})", slice_rows)))
    print()

    # For comparison: same per-(symbol, side) but for the FULL strict population
    print("BASELINE — same slices, NO proposal filter:")
    keys2 = sorted({(r["symbol"], r["side"]) for r in strict})
    for sym, side in keys2:
        slice_rows = [r for r in strict if r["symbol"] == sym and r["side"] == side]
        print(fmt(summarize(f"{sym} {side}", slice_rows)))
    print()

    # Also evaluate on near_close (cleaned: drop yes_no_disagree variants) as out-of-distribution sanity
    near_clean = [
        r for r in all_rows
        if r.get("outcome_label_conf") in {"near_close"}
    ]
    if near_clean:
        nc_trades = [r for r in near_clean if passes_proposal(r)[0]]
        print("SANITY — near_close (clean) subset, proposal applied:")
        print(fmt(summarize("near_close all", near_clean)))
        print(fmt(summarize("near_close + proposal", nc_trades)))
        print()

    # Quick economic translation
    print("ECONOMIC TRANSLATION (per $1 staked, before fees):")
    print(f"  Status quo (0 trades fired)      : $0.00 P&L on {len(strict)} strict signals")
    print(f"  Trade-everything strict          : ${baseline['total_pnl_per_dollar_staked']:+.2f} on {baseline['n']} trades  (avg {baseline['ev_per_dollar']:+.4f}/trade)")
    print(f"  Proposal                         : ${overall['total_pnl_per_dollar_staked']:+.2f} on {overall['n']} trades  (avg {overall['ev_per_dollar']:+.4f}/trade)")
    delta_n = overall["n"] - 0
    delta_pnl = overall["total_pnl_per_dollar_staked"]
    print(f"  Δ vs status quo                  : +{delta_n} trades, +${delta_pnl:.2f} P&L per $1/trade")

    return 0


if __name__ == "__main__":
    sys.exit(main())
