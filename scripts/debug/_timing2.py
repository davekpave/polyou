import csv
from collections import Counter
import statistics

FIELDNAMES = [
    'timestamp','symbol','side','contract_slug','snapshot_price','signal_rr',
    'signal_age_minutes','signal_phase','anchor_distance_percent','signal_priority','signal_quality',
    'slope_z_24h','structure_vol','dynamic_percent_threshold','vol_ratio','percent_vol_ratio',
    'extension_pressure','adaptive_drift_cap','drift_ok','exhaustion_ok','continuation_override',
    'acceleration_ok','pvr_ideal','pvr_terminal','pvr_terminal_cap'
]

with open('logs/execution_log.csv') as f:
    next(f)  # skip stale header
    rows = list(csv.DictReader(f, fieldnames=FIELDNAMES))

print(f"Execution log entries: {len(rows)}")

# Signal phase (where in the 15-min window the entry fired)
phases = [float(r['signal_phase']) for r in rows if r['signal_phase']]
prices = [float(r['snapshot_price']) for r in rows if r['snapshot_price']]
ages   = [float(r['signal_age_minutes']) for r in rows if r['signal_age_minutes']]

print(f"\nEntry phase (0.0=window start, 1.0=window end):")
print(f"  Mean:   {statistics.mean(phases):.3f}")
print(f"  Median: {statistics.median(phases):.3f}")
print(f"  <0.20 (early):  {sum(1 for p in phases if p < 0.20)} trades")
print(f"  0.20-0.40:      {sum(1 for p in phases if 0.20 <= p < 0.40)} trades")
print(f"  0.40-0.60:      {sum(1 for p in phases if 0.40 <= p < 0.60)} trades")
print(f"  0.60-0.80:      {sum(1 for p in phases if 0.60 <= p < 0.80)} trades")
print(f"  >0.80 (late):   {sum(1 for p in phases if p >= 0.80)} trades")

print(f"\nEntry price distribution:")
buckets = Counter(round(int(p*10)/10,1) for p in prices)
for k in sorted(buckets):
    print(f"  {k:.1f}: {'#'*buckets[k]} ({buckets[k]})")

print(f"\nSignal age at entry:")
print(f"  Mean:   {statistics.mean(ages):.1f} min")
print(f"  Median: {statistics.median(ages):.1f} min")
print(f"  <2 min:  {sum(1 for a in ages if a < 2)}")
print(f"  2-5 min: {sum(1 for a in ages if 2 <= a < 5)}")
print(f"  5+ min:  {sum(1 for a in ages if a >= 5)}")

# Win rate by entry price band from exit log (no join needed)
exit_rows = list(csv.DictReader(open('logs/exit_log.csv')))
seen = set()
exits = []
for r in exit_rows:
    if r['token_id'] not in seen:
        seen.add(r['token_id'])
        exits.append(r)

print(f"\nWin rate by entry price (from exit log, {len(exits)} positions):")
bands = [(0.40,0.55,'0.40-0.55'),(0.55,0.65,'0.55-0.65'),(0.65,0.75,'0.65-0.75'),(0.75,1.0,'0.75+')]
for lo, hi, label in bands:
    group = [r for r in exits if lo <= float(r['entry_price']) < hi]
    wins = [r for r in group if r['type'] == 'TAKE_PROFIT']
    if group:
        print(f"  {label}: {len(wins)}/{len(group)} wins = {len(wins)/len(group)*100:.0f}%  avg_win={sum(float(r['profit_cents']) for r in wins)/len(wins):.3f}" if wins else f"  {label}: 0/{len(group)} wins = 0%")
    else:
        print(f"  {label}: no trades")
