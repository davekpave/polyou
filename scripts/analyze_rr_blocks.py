import csv, collections

rows = list(csv.DictReader(open("logs/rr_blocks.csv")))
gates = list(csv.DictReader(open("logs/gate_blocks.csv")))
print(f"rr_blocks rows: {len(rows)}")
print(f"gate_blocks rows: {len(gates)}")
print(f"\nFirst rr ts: {rows[0]['ts_iso']}\nLast rr ts:  {rows[-1]['ts_iso']}")

print("\n=== gate_blocks.csv: gate_name counts ===")
for k, v in collections.Counter(g["gate_name"] for g in gates).most_common():
    print(f"  {k:30s} {v:6d}")

print("\n=== rr_blocks: by symbol/tier ===")
for k, v in collections.Counter((r["symbol"], r["tier"]) for r in rows).most_common():
    print(f"  {k} {v}")

print("\n=== signal_rr distribution by tier (req_rr in parens) ===")
by_tier = collections.defaultdict(list)
for r in rows:
    try:
        by_tier[(r["tier"], r["req_rr"])].append(float(r["signal_rr"]))
    except Exception:
        pass
for (tier, req), vals in sorted(by_tier.items()):
    vals.sort()
    n = len(vals)
    def pct(p, vals=vals, n=n):
        return vals[min(int(n * p), n - 1)]
    print(f"  tier={tier} req={req}  n={n}  min={vals[0]:.3f}  p25={pct(.25):.3f}  p50={pct(.5):.3f}  p75={pct(.75):.3f}  p90={pct(.9):.3f}  p95={pct(.95):.3f}  p99={pct(.99):.3f}  max={vals[-1]:.3f}")

print("\n=== If req_rr were lowered, how many MORE candidates would pass? ===")
for (tier, req), vals in sorted(by_tier.items()):
    req_f = float(req)
    n = len(vals)
    print(f"\n  tier={tier} (current req={req_f:.3f}, n={n})")
    for cand in [0.40, 0.35, 0.30, 0.25, 0.20, 0.15, 0.10]:
        if cand >= req_f:
            continue
        passed = sum(1 for v in vals if v >= cand)
        print(f"    req={cand:.2f}: {passed:5d} would pass ({100*passed/n:.1f}%)")

print("\n=== clob_age_ms distribution (from rr_blocks) ===")
ages = sorted(int(r["clob_age_ms"]) for r in rows if r.get("clob_age_ms", "").isdigit())
n = len(ages)
def apct(p):
    return ages[min(int(n * p), n - 1)]
print(f"  n={n}  min={ages[0]}  p50={apct(.5)}  p75={apct(.75)}  p90={apct(.9)}  p95={apct(.95)}  p99={apct(.99)}  max={ages[-1]}")
