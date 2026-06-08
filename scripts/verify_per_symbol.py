"""Symbol-by-symbol double check of executed vs. blocked populations.

For each symbol, compare:
  (a) Executed trades from logs/execution_log.archive.csv (Apr 14-27)
      - settled outcomes if available, else just signal_rr distribution.
  (b) Blocked candidates from logs/derived/block_outcomes.csv
      with payoff_per_dollar.

Goal: figure out per-symbol rr_min that admits the marginal blocked
candidates only when their EV is non-negative.
"""
import csv, os, collections, statistics

# --- Load blocked candidates ---
blocked = []
for r in csv.DictReader(open("logs/derived/block_outcomes.csv")):
    try:
        blocked.append({
            "rr": float(r["signal_rr"]),
            "won": int(r["block_won"]),
            "payoff": float(r["payoff_per_dollar"]),
            "tier": r["tier"],
            "sym": r["symbol"],
        })
    except Exception:
        pass

# --- Load executed trades (archive) ---
# Header: timestamp,symbol,side,contract_slug,snapshot_price,signal_rr,rr_pass,...
executed = []
with open("logs/execution_log.archive.csv") as f:
    reader = csv.reader(f)
    header = next(reader, None)
    for row in reader:
        if len(row) < 7:
            continue
        sym = row[1]
        if sym not in {"BTCUSD","ETHUSD","SOLUSD","XRPUSD"}:
            continue
        try:
            executed.append({
                "ts": row[0],
                "sym": sym,
                "side": row[2],
                "snap": float(row[4]) if row[4] else None,
                "rr": float(row[5]),
                "rr_pass": row[6],
            })
        except Exception:
            pass

print(f"Loaded {len(blocked)} blocked-with-outcome rows, {len(executed)} executed rows.\n")

# Try to enrich executed with outcomes from block_outcomes if it has them too
# (block_outcomes is ONLY blocks, so we need a separate source for executed PnL)
# Check whether exit_log / execution_log has outcomes for executed trades
exec_outcomes_file = "logs/derived/executed_outcomes.csv"
exec_outcomes = {}
if os.path.exists(exec_outcomes_file):
    for r in csv.DictReader(open(exec_outcomes_file)):
        exec_outcomes[r.get("contract_slug") or r.get("slug")] = r
print(f"executed_outcomes.csv exists: {os.path.exists(exec_outcomes_file)}\n")

# --- Per-symbol breakdown ---
THRESHOLDS = [0.20, 0.25, 0.275, 0.30, 0.35, 0.40, 0.44]

for sym in ["BTCUSD","ETHUSD","SOLUSD","XRPUSD"]:
    print(f"========== {sym} ==========")

    # Executed
    ex = [e for e in executed if e["sym"] == sym]
    if ex:
        rrs = sorted(e["rr"] for e in ex)
        n = len(rrs)
        print(f"  EXECUTED  (archive Apr 14-27): n={n}")
        print(f"    signal_rr  min={rrs[0]:.3f}  q1={rrs[n//4]:.3f}  "
              f"med={rrs[n//2]:.3f}  q3={rrs[(3*n)//4]:.3f}  max={rrs[-1]:.3f}")
        print(f"    fraction with rr>=0.275: {sum(1 for r in rrs if r>=0.275)/n:.1%}")
        print(f"    fraction with rr>=0.30 : {sum(1 for r in rrs if r>=0.30)/n:.1%}")
        print(f"    fraction with rr>=0.40 : {sum(1 for r in rrs if r>=0.40)/n:.1%}")
    else:
        print(f"  EXECUTED: none in archive")

    # Blocked counterfactual
    bl = [b for b in blocked if b["sym"] == sym]
    if bl:
        print(f"  BLOCKED   (rr_blocks Apr 29-30, with outcomes): n={len(bl)}")
        print(f"    {'thr':>6}{'n_pass':>9}{'wr':>9}{'EV/$1':>10}{'sumEV':>9}")
        for thr in THRESHOLDS:
            sub = [b for b in bl if b["rr"] >= thr]
            if len(sub) < 5:
                print(f"    {thr:>6.3f}{len(sub):>9}    (n<5)")
                continue
            wr = sum(b["won"] for b in sub) / len(sub)
            ev = sum(b["payoff"] for b in sub) / len(sub)
            tot = sum(b["payoff"] for b in sub)
            print(f"    {thr:>6.3f}{len(sub):>9}{wr:>9.1%}{ev:>+10.4f}{tot:>+9.2f}")
    else:
        print(f"  BLOCKED: none in block_outcomes")
    print()

# --- Summary recommendation ---
print("\n========== SUGGESTED PER-SYMBOL rr_min ==========")
print("For each symbol, find the lowest threshold where:")
print("  - blocked-cohort EV/$1 >= 0  AND  n_pass >= 20")
print("This is the threshold at which expanding admits non-negative-EV trades.\n")
for sym in ["BTCUSD","ETHUSD","SOLUSD","XRPUSD"]:
    bl = [b for b in blocked if b["sym"] == sym]
    if not bl:
        print(f"  {sym}: no data")
        continue
    best = None
    for thr in [0.20, 0.225, 0.25, 0.275, 0.30, 0.325, 0.35, 0.375, 0.40, 0.425, 0.44, 0.50]:
        sub = [b for b in bl if b["rr"] >= thr]
        if len(sub) < 20:
            continue
        ev = sum(b["payoff"] for b in sub) / len(sub)
        if ev >= 0:
            best = (thr, len(sub), ev)
            break
    if best:
        print(f"  {sym}: rr_min={best[0]:.3f}  (n_blocked_pass={best[1]}, ev/$1={best[2]:+.4f})")
    else:
        print(f"  {sym}: NO threshold up to 0.50 yields non-negative-EV blocked cohort  -> consider DISABLE or set rr_min very high")
