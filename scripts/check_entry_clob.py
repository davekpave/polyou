"""Compare entry-side CLOB book vs snapshot_price for UP vs DOWN, to test
the stale-snapshot hypothesis for the UP-side win-rate failure.
"""
import csv
import statistics


def f(x):
    try:
        return float(x)
    except Exception:
        return None


r = list(csv.DictReader(open("logs/decision_log.csv")))
by_side = {"UP": [], "DOWN": []}
for row in r:
    side = row["side"]
    if side not in by_side:
        continue
    by_side[side].append(
        {
            "sym": row["symbol"],
            "snap": f(row["snapshot_price"]),
            "ask": f(row["best_ask"]),
            "bid": f(row["best_bid"]),
            "age": f(row["clob_age_ms"]),
            "spread": f(row["spread_bps"]),
        }
    )

for side, rows in by_side.items():
    print(f"\n=== {side} (n={len(rows)}) ===")
    snaps = [x["snap"] for x in rows if x["snap"] is not None]
    asks = [x["ask"] for x in rows if x["ask"] is not None]
    bids = [x["bid"] for x in rows if x["bid"] is not None]
    ages = [x["age"] for x in rows if x["age"] is not None]
    sprs = [x["spread"] for x in rows if x["spread"] is not None]
    diffs = [x["ask"] - x["snap"] for x in rows if x["ask"] is not None and x["snap"] is not None]
    print(
        f"snapshot:  mean={statistics.mean(snaps):.4f} median={statistics.median(snaps):.4f} "
        f"range=[{min(snaps):.3f},{max(snaps):.3f}]"
    )
    if asks:
        print(
            f"best_ask:  mean={statistics.mean(asks):.4f} median={statistics.median(asks):.4f} "
            f"range=[{min(asks):.3f},{max(asks):.3f}]  n={len(asks)}"
        )
        print(f"best_bid:  mean={statistics.mean(bids):.4f} median={statistics.median(bids):.4f} n={len(bids)}")
        print(
            f"ask-snap:  mean={statistics.mean(diffs):+.4f} median={statistics.median(diffs):+.4f} "
            f"range=[{min(diffs):+.3f},{max(diffs):+.3f}]"
        )
        print(f"spread_bp: mean={statistics.mean(sprs):.0f} median={statistics.median(sprs):.0f}")
        print(f"clob_age:  mean={statistics.mean(ages):.0f}ms median={statistics.median(ages):.0f}ms max={max(ages):.0f}ms")
    else:
        print("  no live book data captured at decision")

print("\n--- per-row UP listing ---")
print(f"  {'sym':7s}  {'snap':>6s}  {'ask':>6s}  {'bid':>6s}  {'delta':>7s}  {'spr_bps':>8s}  {'age_ms':>8s}")
for x in by_side["UP"]:
    sd = (x["ask"] - x["snap"]) if (x["ask"] is not None and x["snap"] is not None) else None
    print(
        f"  {x['sym']:7s}  {x['snap']!s:>6}  {x['ask']!s:>6}  {x['bid']!s:>6}  "
        f"{sd!s:>7}  {x['spread']!s:>8}  {x['age']!s:>8}"
    )

print("\n--- per-row DOWN listing ---")
print(f"  {'sym':7s}  {'snap':>6s}  {'ask':>6s}  {'bid':>6s}  {'delta':>7s}  {'spr_bps':>8s}  {'age_ms':>8s}")
for x in by_side["DOWN"]:
    sd = (x["ask"] - x["snap"]) if (x["ask"] is not None and x["snap"] is not None) else None
    print(
        f"  {x['sym']:7s}  {x['snap']!s:>6}  {x['ask']!s:>6}  {x['bid']!s:>6}  "
        f"{sd!s:>7}  {x['spread']!s:>8}  {x['age']!s:>8}"
    )
