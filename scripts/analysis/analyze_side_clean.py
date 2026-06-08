"""Clean UP vs DOWN analysis matching exits to entries via timestamp + entry_price."""
import csv

# Load entries (has 'side' column)
entries = []
with open('logs/execution_log.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            entries.append({
                'ts': float(row['timestamp']),
                'symbol': row['symbol'],
                'side': row['side'],
                'entry_price': float(row['snapshot_price']),
            })
        except (ValueError, KeyError):
            continue

# Load exits (has 'token_id' but no side)
exits = []
with open('logs/exit_log.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            ep = float(row['entry_price'])
            xp = float(row['exit_price'])
            if xp < 0.05:  # filter stuck positions
                continue
            exits.append({
                'ts': float(row['timestamp']),
                'entry_price': ep,
                'exit_price': xp,
                'pnl': float(row['profit_cents']),
            })
        except (ValueError, KeyError):
            continue

# Match each exit to nearest entry: same entry_price (±0.01) and exit_ts > entry_ts within 20 min
up_w = up_l = down_w = down_l = 0
up_pnl = down_pnl = 0.0
unmatched = 0
matched_entries = set()

for ex in exits:
    best = None
    best_diff = float('inf')
    for i, en in enumerate(entries):
        if i in matched_entries:
            continue
        if abs(en['entry_price'] - ex['entry_price']) > 0.01:
            continue
        dt = ex['ts'] - en['ts']
        if dt < 0 or dt > 1200:
            continue
        if dt < best_diff:
            best_diff = dt
            best = i
    if best is None:
        unmatched += 1
        continue
    matched_entries.add(best)
    side = entries[best]['side']
    won = ex['pnl'] > 0
    if side == 'UP':
        if won: up_w += 1
        else: up_l += 1
        up_pnl += ex['pnl']
    else:
        if won: down_w += 1
        else: down_l += 1
        down_pnl += ex['pnl']

up_total = up_w + up_l
down_total = down_w + down_l

print(f"Entries: {len(entries)} | Exits: {len(exits)} | Matched: {up_total + down_total} | Unmatched: {unmatched}")
print()
print(f"UP   : {up_total} trades | {up_w}W-{up_l}L | WR={100*up_w/max(up_total,1):.1f}% | PnL=${up_pnl:.2f} | Avg=${up_pnl/max(up_total,1):.3f}")
print(f"DOWN : {down_total} trades | {down_w}W-{down_l}L | WR={100*down_w/max(down_total,1):.1f}% | PnL=${down_pnl:.2f} | Avg=${down_pnl/max(down_total,1):.3f}")
print()
print(f"Total PnL: ${up_pnl + down_pnl:.2f}")
