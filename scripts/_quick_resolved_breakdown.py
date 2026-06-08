import csv
from collections import defaultdict

agg = defaultdict(lambda: {"n": 0, "w": 0, "ev": 0.0})
with open("logs/gate_blocks_resolved.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["would_have_won"] not in ("0", "1"):
            continue
        try:
            ev = float(r["payoff_per_dollar"])
        except ValueError:
            continue
        k = r["gate_name"]
        agg[k]["n"] += 1
        agg[k]["w"] += int(r["would_have_won"] == "1")
        agg[k]["ev"] += ev

print(f"{'gate':<25} {'n':>5} {'win%':>6} {'EV/$':>9}")
for k, v in sorted(agg.items(), key=lambda x: -x[1]["n"]):
    wr = v["w"] / v["n"] * 100
    ev = v["ev"] / v["n"]
    print(f"{k:<25} {v['n']:>5} {wr:>5.1f}% {ev:>+9.4f}")

print()
print("--- gate_blocks by symbol ---")
agg2 = defaultdict(lambda: {"n": 0, "w": 0, "ev": 0.0})
with open("logs/gate_blocks_resolved.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["would_have_won"] not in ("0", "1"):
            continue
        try:
            ev = float(r["payoff_per_dollar"])
        except ValueError:
            continue
        k = r["symbol"]
        agg2[k]["n"] += 1
        agg2[k]["w"] += int(r["would_have_won"] == "1")
        agg2[k]["ev"] += ev

for k, v in sorted(agg2.items(), key=lambda x: -x[1]["n"]):
    wr = v["w"] / v["n"] * 100
    ev = v["ev"] / v["n"]
    print(f"{k:<10} n={v['n']:>5} win={wr:>5.1f}% EV/$={ev:>+.4f}")

print()
print("--- rr_blocks by symbol/side ---")
agg3 = defaultdict(lambda: {"n": 0, "w": 0, "ev": 0.0})
with open("logs/rr_blocks_resolved.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["would_have_won"] not in ("0", "1"):
            continue
        try:
            ev = float(r["payoff_per_dollar"])
        except ValueError:
            continue
        k = (r["symbol"], r["side"])
        agg3[k]["n"] += 1
        agg3[k]["w"] += int(r["would_have_won"] == "1")
        agg3[k]["ev"] += ev

for k, v in sorted(agg3.items(), key=lambda x: -x[1]["n"]):
    wr = v["w"] / v["n"] * 100
    ev = v["ev"] / v["n"]
    print(f"{k[0]:<8} {k[1]:<5} n={v['n']:>5} win={wr:>5.1f}% EV/$={ev:>+.4f}")
