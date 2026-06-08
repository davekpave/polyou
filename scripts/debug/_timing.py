import csv
from datetime import datetime
from collections import Counter

rows = list(csv.DictReader(open('logs/execution_log.csv')))
print(f"Total execution log entries: {len(rows)}")
print(f"Columns: {list(rows[0].keys()) if rows else 'none'}")

if not rows:
    exit()

# Print first row to see all fields
print("\nSample row:")
for k, v in rows[0].items():
    print(f"  {k}: {v}")

# Signal phase distribution
phases = []
for r in rows:
    try:
        phases.append(float(r.get('signal_phase', 0) or 0))
    except:
        pass

if phases:
    import statistics
    print(f"\nSignal phase (0=window start, 1=window end):")
    print(f"  Min:    {min(phases):.3f}")
    print(f"  Max:    {max(phases):.3f}")
    print(f"  Mean:   {statistics.mean(phases):.3f}")
    print(f"  Median: {statistics.median(phases):.3f}")
    
    buckets = Counter()
    for p in phases:
        b = int(p * 10) / 10  # bucket to 0.0, 0.1, 0.2 etc
        buckets[b] += 1
    print("\n  Phase distribution (0.0=early, 1.0=very late):")
    for k in sorted(buckets):
        bar = '#' * buckets[k]
        print(f"    {k:.1f}: {bar} ({buckets[k]})")

# Entry price distribution
prices = []
for r in rows:
    try:
        prices.append(float(r.get('snapshot_price', 0) or 0))
    except:
        pass

if prices:
    print(f"\nEntry price distribution:")
    p_buckets = Counter()
    for p in prices:
        b = round(int(p * 10) / 10, 1)
        p_buckets[b] += 1
    for k in sorted(p_buckets):
        bar = '#' * p_buckets[k]
        print(f"    {k:.1f}: {bar} ({p_buckets[k]})")

# Signal age
ages = []
for r in rows:
    try:
        ages.append(float(r.get('signal_age_minutes', 0) or 0))
    except:
        pass

if ages:
    import statistics
    print(f"\nSignal age (minutes since signal formed):")
    print(f"  Mean:   {statistics.mean(ages):.1f} min")
    print(f"  Median: {statistics.median(ages):.1f} min")
    print(f"  Max:    {max(ages):.1f} min")

# Win/loss by phase — join with exit log
exit_rows = list(csv.DictReader(open('logs/exit_log.csv')))
seen = set()
exits = {}
for r in exit_rows:
    tid = r['token_id']
    if tid not in seen:
        seen.add(tid)
        exits[tid] = r

print("\nWin/loss by entry phase:")
phase_wins = {}
phase_total = {}
for r in rows:
    try:
        tid = r.get('token_id') or r.get('contract_slug') or ''
        phase = float(r.get('signal_phase', 0) or 0)
        bucket = int(phase * 5) / 5  # 0.0, 0.2, 0.4, 0.6, 0.8
        
        # Try to find the exit for this entry
        ex = exits.get(tid)
        if ex:
            won = ex['type'] == 'TAKE_PROFIT'
            phase_wins[bucket] = phase_wins.get(bucket, 0) + (1 if won else 0)
            phase_total[bucket] = phase_total.get(bucket, 0) + 1
    except:
        pass

for b in sorted(phase_total):
    w = phase_wins.get(b, 0)
    t = phase_total[b]
    wr = w/t*100 if t else 0
    print(f"  Phase {b:.1f}-{b+0.2:.1f}: {w}/{t} wins = {wr:.0f}%")
