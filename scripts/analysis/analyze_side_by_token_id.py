"""Analyze UP vs DOWN using token_id join (once new execution log format is active)."""
import csv
from collections import defaultdict

# Load entries with token_id (NEW FORMAT)
entries_by_token = {}
try:
    with open('logs/execution_log.csv', 'r') as f:
        reader = csv.DictReader(f)
        # Check if new format with token_id
        if 'token_id' not in reader.fieldnames:
            print("⚠️  execution_log.csv doesn't have token_id column yet.")
            print("Wait for the next trade to be logged with the new format.")
            exit(1)
        
        for row in reader:
            try:
                token_id = row['token_id']
                entries_by_token[token_id] = {
                    'ts': float(row['timestamp']),
                    'symbol': row['symbol'],
                    'side': row['side'],
                    'entry_price': float(row['snapshot_price']),
                    'quality': float(row['signal_quality']),
                }
            except (ValueError, KeyError) as e:
                continue
except FileNotFoundError:
    print("❌ execution_log.csv not found")
    exit(1)

# Load exits with token_id
exits_by_token = {}
with open('logs/exit_log.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            ep = float(row['entry_price'])
            xp = float(row['exit_price'])
            if xp < 0.05:  # filter stuck positions
                continue
            token_id = row['token_id']
            exits_by_token[token_id] = {
                'ts': float(row['timestamp']),
                'entry_price': ep,
                'exit_price': xp,
                'pnl': float(row['profit_cents']),
            }
        except (ValueError, KeyError):
            continue

# Perfect join on token_id
up_w = up_l = down_w = down_l = 0
up_pnl = down_pnl = 0.0
up_quality_wins = []
up_quality_losses = []
down_quality_wins = []
down_quality_losses = []

for token_id, entry in entries_by_token.items():
    if token_id not in exits_by_token:
        continue
    
    exit_data = exits_by_token[token_id]
    side = entry['side']
    won = exit_data['pnl'] > 0
    quality = entry['quality']
    
    if side == 'UP':
        if won:
            up_w += 1
            up_quality_wins.append(quality)
        else:
            up_l += 1
            up_quality_losses.append(quality)
        up_pnl += exit_data['pnl']
    else:
        if won:
            down_w += 1
            down_quality_wins.append(quality)
        else:
            down_l += 1
            down_quality_losses.append(quality)
        down_pnl += exit_data['pnl']

up_total = up_w + up_l
down_total = down_w + down_l
total_matched = up_total + down_total

print(f"✅ Clean join on token_id")
print(f"Entries: {len(entries_by_token)} | Exits: {len(exits_by_token)} | Matched: {total_matched}")
print()

if up_total > 0:
    up_avg_qual_w = sum(up_quality_wins) / len(up_quality_wins) if up_quality_wins else 0
    up_avg_qual_l = sum(up_quality_losses) / len(up_quality_losses) if up_quality_losses else 0
    print(f"UP   : {up_total} trades | {up_w}W-{up_l}L | WR={100*up_w/up_total:.1f}%")
    print(f"       PnL=${up_pnl:.2f} | Avg=${up_pnl/up_total:.3f}")
    print(f"       Quality: Winners avg {up_avg_qual_w:.0f} | Losers avg {up_avg_qual_l:.0f}")
else:
    print(f"UP   : 0 trades")

print()

if down_total > 0:
    down_avg_qual_w = sum(down_quality_wins) / len(down_quality_wins) if down_quality_wins else 0
    down_avg_qual_l = sum(down_quality_losses) / len(down_quality_losses) if down_quality_losses else 0
    print(f"DOWN : {down_total} trades | {down_w}W-{down_l}L | WR={100*down_w/down_total:.1f}%")
    print(f"       PnL=${down_pnl:.2f} | Avg=${down_pnl/down_total:.3f}")
    print(f"       Quality: Winners avg {down_avg_qual_w:.0f} | Losers avg {down_avg_qual_l:.0f}")
else:
    print(f"DOWN : 0 trades")

print()
print(f"Total PnL: ${up_pnl + down_pnl:.2f}")

# Overall recommendation
if total_matched >= 30:  # Need reasonable sample
    if up_total >= 15 and down_total >= 15:
        if up_w/up_total > down_w/down_total + 0.10:  # 10%+ edge
            print(f"\n📊 Recommendation: UP side shows {100*up_w/up_total:.1f}% vs {100*down_w/down_total:.1f}% → trade UP only")
        elif down_w/down_total > up_w/up_total + 0.10:
            print(f"\n📊 Recommendation: DOWN side shows {100*down_w/down_total:.1f}% vs {100*up_w/up_total:.1f}% → trade DOWN only")
        else:
            print(f"\n📊 Recommendation: Sides similar ({100*up_w/up_total:.1f}% vs {100*down_w/down_total:.1f}%) → trade BOTH")
    else:
        print("\n⚠️  Need more data on both sides (min 15 each) for confident recommendation")
else:
    print(f"\n⚠️  Only {total_matched} matched trades - need 30+ for reliable analysis")
