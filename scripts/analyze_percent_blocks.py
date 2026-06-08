"""Analyze percent_ok gate blocks.

For each symbol:
- Distribution of observed percent_move at the moment of block.
- How close they came to the static MIN_PERCENT_MOVE floor.
- How many would have passed at various lower floors.

Note: percent_ok actually requires percent_move >= max(MIN_PERCENT_MOVE,
PERCENT_VOL_MULTIPLIER * volatility), and we only have the observed move
(not the dynamic threshold). So MIN_PERCENT_MOVE is a *lower bound* on
what they had to clear. If the observed values cluster well below even
this floor, we know the gate is binding hard.
"""
import csv
import collections
import json

MIN_PERCENT_MOVE = {
    "BTCUSD": 0.0006,
    "ETHUSD": 0.0010,
    "SOLUSD": 0.0018,
    "XRPUSD": 0.0018,
}

rows = list(csv.DictReader(open("logs/gate_blocks.csv")))
po = [r for r in rows if r["gate_name"] == "percent_ok"]
print(f"Total percent_ok blocks: {len(po)}")

print("\n=== percent_move distribution by symbol (and pct of static floor) ===")
print(f"{'symbol':<10}{'n':>6}{'floor':>10}{'p50':>12}{'p75':>12}{'p90':>12}{'p95':>12}{'max':>12}{'pass_floor%':>14}")
by_sym = collections.defaultdict(list)
for r in po:
    try:
        by_sym[r["symbol"]].append(float(r["percent_move"]))
    except Exception:
        pass

for sym, vals in sorted(by_sym.items()):
    vals.sort()
    n = len(vals)
    floor = MIN_PERCENT_MOVE.get(sym, 0)
    def pp(p, vals=vals, n=n):
        return vals[min(int(n * p), n - 1)]
    passed_floor = sum(1 for v in vals if v >= floor)
    print(f"{sym:<10}{n:>6}{floor:>10.5f}{pp(.5):>12.5f}{pp(.75):>12.5f}{pp(.9):>12.5f}{pp(.95):>12.5f}{vals[-1]:>12.5f}{100*passed_floor/n:>13.1f}%")

print("\n=== If MIN_PERCENT_MOVE floor were lowered, how many MORE blocks would have passed? ===")
print("(Reminder: dynamic floor is max(MIN, vol-scaled), so this is an upper bound on permissivity.)")
for sym, vals in sorted(by_sym.items()):
    floor = MIN_PERCENT_MOVE.get(sym, 0)
    n = len(vals)
    print(f"\n  {sym} (current floor={floor:.5f}, n={n})")
    for cand in [floor*0.75, floor*0.5, floor*0.25, floor*0.1]:
        passed = sum(1 for v in vals if v >= cand)
        print(f"    floor={cand:.5f} ({100*cand/floor:.0f}% of current): {passed:5d} would pass ({100*passed/n:.1f}%)")

# Also: zero-move blocks?
print("\n=== Tiny moves (anchor noise?) ===")
total = sum(1 for r in po if r.get("percent_move",""))
near_zero = sum(1 for r in po if r.get("percent_move","") and float(r["percent_move"]) < 0.0001)
print(f"  percent_move < 0.0001 (i.e. <0.01%):  {near_zero} / {total}  ({100*near_zero/total:.1f}%)")
near_zero5 = sum(1 for r in po if r.get("percent_move","") and float(r["percent_move"]) < 0.00005)
print(f"  percent_move < 0.00005 (i.e. <0.005%): {near_zero5} / {total}  ({100*near_zero5/total:.1f}%)")
