"""Diagnostic: does snapshot_price predict outcome resolution quality?

If low-sp signals systematically resolve into 'near_close' (noisier) labels
more often than the population, then the proposed SIDE_PRICE_CAP rule is
biased toward structurally noisier markets — a hidden failure mode.

Read-only. No state mutated.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

INPUT = Path(__file__).resolve().parent.parent / "logs" / "derived" / "block_outcomes.csv"

SP_BUCKETS = [
    (0.00, 0.70, "0.00-0.70"),
    (0.70, 0.80, "0.70-0.80"),
    (0.80, 0.85, "0.80-0.85"),
    (0.85, 0.90, "0.85-0.90"),
    (0.90, 0.95, "0.90-0.95"),
    (0.95, 1.01, "0.95-1.00"),
]


def bucket_for(sp: float) -> str:
    for lo, hi, name in SP_BUCKETS:
        if lo <= sp < hi:
            return name
    return "??"


def to_float(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    with INPUT.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Group label_conf into buckets
    def label_class(lc: str) -> str:
        if lc == "strict":
            return "strict"
        if lc.startswith("near_close") and "yes_no_disagree" in lc:
            return "broken"
        if lc.startswith("near_close"):
            return "near_close"
        if lc == "stale_terminal":
            return "stale"
        return "other"

    print(f"Loaded {len(rows)} rows from {INPUT.name}\n")

    # Overall label_conf distribution
    overall = Counter(label_class(r["outcome_label_conf"]) for r in rows)
    total = sum(overall.values())
    print("OVERALL outcome_label_conf distribution:")
    for k in ("strict", "near_close", "broken", "stale", "other"):
        n = overall.get(k, 0)
        print(f"  {k:12s}  {n:5d}  ({n/total*100:5.1f}%)")
    print()

    # Crosstab: snapshot_price bucket × label_class
    print("=" * 88)
    print("CROSSTAB: snapshot_price bucket × outcome_label_conf class")
    print("=" * 88)
    print(f"  {'sp bucket':12s}  {'n':>6s}  {'strict%':>8s}  {'near%':>7s}  {'broken%':>8s}  {'stale%':>7s}  {'win%':>7s}  {'meanSP':>7s}")
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        sp = to_float(r["snapshot_price"])
        if sp is None:
            continue
        by_bucket[bucket_for(sp)].append(r)
    for _, _, name in SP_BUCKETS:
        bucket_rows = by_bucket.get(name, [])
        n = len(bucket_rows)
        if n == 0:
            print(f"  {name:12s}  {0:6d}")
            continue
        cls = Counter(label_class(r["outcome_label_conf"]) for r in bucket_rows)
        wins = sum(1 for r in bucket_rows if to_float(r["block_won"]) == 1.0)
        mean_sp = sum(to_float(r["snapshot_price"]) or 0.0 for r in bucket_rows) / n
        print(
            f"  {name:12s}  {n:6d}  "
            f"{cls.get('strict',0)/n*100:7.1f}%  "
            f"{cls.get('near_close',0)/n*100:6.1f}%  "
            f"{cls.get('broken',0)/n*100:7.1f}%  "
            f"{cls.get('stale',0)/n*100:6.1f}%  "
            f"{wins/n*100:6.1f}%  "
            f"{mean_sp:6.3f}"
        )
    print()

    # Same crosstab per (symbol, side) — only show pairs with n>=100
    print("=" * 88)
    print("CROSSTAB by (symbol, side):  strict% as function of sp bucket")
    print("=" * 88)
    pairs = sorted({(r["symbol"], r["side"]) for r in rows})
    for sym, side in pairs:
        sub = [r for r in rows if r["symbol"] == sym and r["side"] == side]
        if len(sub) < 100:
            continue
        print(f"\n  {sym} {side}  (n={len(sub)})")
        print(f"    {'sp bucket':12s}  {'n':>5s}  {'strict%':>8s}  {'near%':>7s}  {'win%':>7s}")
        for _, _, name in SP_BUCKETS:
            bucket = [r for r in sub if r.get("snapshot_price") and bucket_for(float(r["snapshot_price"])) == name]
            n = len(bucket)
            if n == 0:
                continue
            cls = Counter(label_class(r["outcome_label_conf"]) for r in bucket)
            wins = sum(1 for r in bucket if to_float(r["block_won"]) == 1.0)
            print(
                f"    {name:12s}  {n:5d}  "
                f"{cls.get('strict',0)/n*100:7.1f}%  "
                f"{cls.get('near_close',0)/n*100:6.1f}%  "
                f"{wins/n*100:6.1f}%"
            )

    print()
    print("INTERPRETATION GUIDE:")
    print("  If strict% is roughly constant across sp buckets:")
    print("    -> Low sp does NOT preferentially pick noisier markets.")
    print("    -> Strict-only EV result is real. Proposal is sound.")
    print("    -> GO to Phase A.2 (live observer).")
    print("  If strict% drops sharply for low sp buckets:")
    print("    -> Low sp signals are biased toward noisier markets.")
    print("    -> The +EV in strict-only is partly artifact of label filter.")
    print("    -> Need quality predictor or much tighter caps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
