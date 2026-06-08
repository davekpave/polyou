"""Analyze UP vs DOWN performance."""
import csv
from collections import defaultdict

def parse_execution_log():
    """Parse execution_log.csv to get entry details with side."""
    trades = {}
    with open('logs/execution_log.csv', 'r') as f:
        reader = csv.reader(f)
        next(reader, None)  # Skip header
        for row in reader:
            if len(row) < 5:
                continue
            try:
                timestamp = float(row[0])
                symbol = row[1]
                side = row[2]  # UP or DOWN
                entry_price = float(row[4])  # snapshot_price
                
                # Use entry_price + timestamp as key (rounded to match)
                key = (round(entry_price, 2), int(timestamp / 60))  # Round to minute
                trades[key] = {
                    'symbol': symbol,
                    'side': side,
                    'entry_price': entry_price,
                }
            except (ValueError, IndexError):
                continue
    return trades

def parse_exit_log():
    """Parse exit_log.csv to get exit outcomes."""
    exits = []
    with open('logs/exit_log.csv', 'r') as f:
        reader = csv.reader(f)
        next(reader, None)  # Skip header
        for row in reader:
            if len(row) < 6:
                continue
            try:
                timestamp = float(row[0])
                entry_price = float(row[3])
                exit_price = float(row[4])
                pnl = float(row[5])
                
                # Filter out stuck positions (exit_price < 0.05)
                if exit_price < 0.05:
                    continue
                
                exits.append({
                    'timestamp': timestamp,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'won': pnl > 0
                })
            except (ValueError, IndexError):
                continue
    return exits

def match_and_analyze():
    """Match exits to entries and analyze by direction."""
    entries = parse_execution_log()
    exits = parse_exit_log()
    
    up_wins = 0
    up_losses = 0
    up_pnl = 0.0
    
    down_wins = 0
    down_losses = 0
    down_pnl = 0.0
    
    unmatched = 0
    
    for exit_data in exits:
        # Try to match by entry price and timestamp
        entry_price = round(exit_data['entry_price'], 2)
        timestamp_minute = int(exit_data['timestamp'] / 60)
        
        # Check current minute and previous few minutes
        matched = False
        for min_offset in range(0, 20):  # Check back 20 minutes
            key = (entry_price, timestamp_minute - min_offset)
            if key in entries:
                entry = entries[key]
                side = entry['side']
                
                if side == 'UP':
                    if exit_data['won']:
                        up_wins += 1
                    else:
                        up_losses += 1
                    up_pnl += exit_data['pnl']
                else:  # DOWN
                    if exit_data['won']:
                        down_wins += 1
                    else:
                        down_losses += 1
                    down_pnl += exit_data['pnl']
                
                matched = True
                break
        
        if not matched:
            unmatched += 1
    
    # Print results
    print("=" * 60)
    print("UP vs DOWN Performance Analysis")
    print("=" * 60)
    print()
    
    up_total = up_wins + up_losses
    down_total = down_wins + down_losses
    
    if up_total > 0:
        up_wr = (up_wins / up_total) * 100
        up_avg_pnl = up_pnl / up_total
        print(f"UP Trades:")
        print(f"  Total: {up_total}")
        print(f"  Wins: {up_wins} | Losses: {up_losses}")
        print(f"  Win Rate: {up_wr:.1f}%")
        print(f"  Avg P&L: ${up_avg_pnl:.3f}")
        print(f"  Total P&L: ${up_pnl:.2f}")
    else:
        print("UP Trades: No data")
    
    print()
    
    if down_total > 0:
        down_wr = (down_wins / down_total) * 100
        down_avg_pnl = down_pnl / down_total
        print(f"DOWN Trades:")
        print(f"  Total: {down_total}")
        print(f"  Wins: {down_wins} | Losses: {down_losses}")
        print(f"  Win Rate: {down_wr:.1f}%")
        print(f"  Avg P&L: ${down_avg_pnl:.3f}")
        print(f"  Total P&L: ${down_pnl:.2f}")
    else:
        print("DOWN Trades: No data")
    
    print()
    print(f"Unmatched exits: {unmatched}")
    print("=" * 60)

if __name__ == '__main__':
    match_and_analyze()
