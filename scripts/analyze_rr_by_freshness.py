"""Compare signal_rr distribution across clob_age_ms quartiles, per tier.

Hypothesis: if stale snapshots eat R:R, fresher quartiles should show
materially higher signal_rr, and more candidates within each tier should
clear that tier's req_rr threshold.
"""
import csv
import collections

rows = list(csv.DictReader(open("logs/rr_blocks.csv")))


def parse(r):
    try:
        age = int(r["clob_age_ms"])
        rr = float(r["signal_rr"])
        req = float(r["req_rr"])
        return age, rr, req, r["tier"], r["symbol"]
    except Exception:
        return None


parsed = [p for p in (parse(r) for r in rows) if p is not None]
print(f"Total parsed rows: {len(parsed)}")

# overall quartile cutoffs on clob_age_ms
ages_sorted = sorted(p[0] for p in parsed)
n = len(ages_sorted)
def at(p): return ages_sorted[min(int(n * p), n - 1)]
q1, q2, q3 = at(0.25), at(0.50), at(0.75)
print(f"\nclob_age_ms quartile cutoffs:  Q1={q1}  Q2(median)={q2}  Q3={q3}")

def bucket(age):
    if age <= q1: return "Q1_freshest"
    if age <= q2: return "Q2"
    if age <= q3: return "Q3"
    return "Q4_stalest"

# group: (tier, quartile) -> list of signal_rr
groups = collections.defaultdict(list)
req_by_tier = {}
for age, rr, req, tier, sym in parsed:
    groups[(tier, bucket(age))].append(rr)
    req_by_tier[tier] = req

print("\n=== signal_rr stats by tier and freshness quartile ===")
print(f"{'tier':<10}{'quartile':<14}{'n':>6}{'mean':>8}{'p50':>8}{'p75':>8}{'p90':>8}{'p95':>8}{'max':>8}{'pass%':>8}")
for tier in ["VIP", "STANDARD", "STRICT"]:
    req = req_by_tier.get(tier)
    for q in ["Q1_freshest", "Q2", "Q3", "Q4_stalest"]:
        vals = sorted(groups[(tier, q)])
        if not vals:
            continue
        m = len(vals)
        mean = sum(vals) / m
        def pp(p): return vals[min(int(m * p), m - 1)]
        passed = sum(1 for v in vals if v >= req) if req else 0
        pct = 100 * passed / m
        print(f"{tier:<10}{q:<14}{m:>6}{mean:>8.3f}{pp(.5):>8.3f}{pp(.75):>8.3f}{pp(.9):>8.3f}{pp(.95):>8.3f}{vals[-1]:>8.3f}{pct:>7.1f}%")
    print()

# also compare freshest decile vs stalest decile, all tiers combined
print("=== Freshest 10% vs stalest 10% (all tiers, normalised as signal_rr / req_rr) ===")
def normval(p):
    age, rr, req, tier, sym = p
    return rr / req if req else 0
parsed_sorted_by_age = sorted(parsed, key=lambda p: p[0])
n10 = max(1, n // 10)
fresh = parsed_sorted_by_age[:n10]
stale = parsed_sorted_by_age[-n10:]
def stats(group, label):
    norms = sorted(normval(p) for p in group)
    rrs   = sorted(p[1]      for p in group)
    ages  = [p[0] for p in group]
    mean_norm = sum(norms) / len(norms)
    mean_rr   = sum(rrs)   / len(rrs)
    mean_age  = sum(ages)  / len(ages)
    print(f"  {label:<14} n={len(group):5d}  mean_age_ms={mean_age:6.0f}  mean_signal_rr={mean_rr:.4f}  mean_rr/req={mean_norm:.3f}")
stats(fresh, "freshest 10%")
stats(stale, "stalest 10%")
