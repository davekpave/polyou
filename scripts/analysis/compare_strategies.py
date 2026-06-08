"""Compare old strategy vs new strategy performance."""
import csv

def parse_execution_log():
    """Parse execution_log.csv to get entry details."""
    trades = []
    with open('logs/execution_log.csv', 'r') as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 10:
                continue
            try:
                timestamp = float(row[0])
                symbol = row[1]
                side = row[2]
                entry_price = float(row[4])
                quality = float(row[9])
                
                trades.append({
                    'timestamp': timestamp,
                    'symbol': symbol,
                    'side': side,
                    'entry_price': entry_price,
                    'quality': quality,
                })
            except (ValueError, IndexError):
                continue
    return trades

def parse_exit_log():
    """Parse exit_log.csv to get exit outcomes."""
    exits = []
    with open('logs/exit_log.csv', 'r') as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 6:
                continue
            try:
                timestamp = float(row[0])
                entry_price = float(row[3])
                pnl = float(row[5])
                
                exits.append({
                    'timestamp': timestamp,
                    'entry_price': entry_price,
                    'pnl': pnl,
                    'won': pnl > 0
                })
            except (ValueError, IndexError):
                continue
    return exits

def match_trades(entries, exits):
    """Match exits to entries."""
    matched = []
    for exit_data in exits:
        best_match = None
        best_diff = float('inf')
        
        for entry_data in entries:
            price_diff = abs(entry_data['entry_price'] - exit_data['entry_price'])
            if price_diff > 0.01:
                continue
            
            time_diff = exit_data['timestamp'] - entry_data['timestamp']
            if time_diff < 0 or time_diff > 1200:
                continue
            
            if time_diff < best_diff:
                best_diff = time_diff
                best_match = entry_data
        
        if best_match:
            matched.append({**best_match, **exit_data})
    
    return matched

def apply_old_strategy(trades):
    """Apply old strategy filters."""
    # Old strategy: ETH+BTC, DOWN only, Entry >=0.65, Quality 500-1000
    filtered = []
    for t in trades:
        if t['symbol'] not in ['ETHUSD', 'BTCUSD']:
            continue
        if t['side'] != 'DOWN':
            continue
        if t['entry_price'] < 0.65:
            continue
        if t['quality'] < 500:
            continue
        # No max quality filter in old (we only warned)
        filtered.append(t)
    return filtered

def apply_new_strategy(trades):
    """Apply new strategy filters."""
    # New strategy: ETH ONLY, DOWN only, Entry >=0.65, NO quality filter
    filtered = []
    for t in trades:
        if t['symbol'] != 'ETHUSD':
            continue
        if t['side'] != 'DOWN':
            continue
        if t['entry_price'] < 0.65:
            continue
        # No quality filter
        filtered.append(t)
    return filtered

def calculate_stats(trades):
    """Calculate win rate and P&L stats."""
    if not trades:
        return None
    
    wins = [t for t in trades if t['won']]
    losses = [t for t in trades if not t['won']]
    
    total_pnl = sum(t['pnl'] for t in trades)
    avg_pnl = total_pnl / len(trades)
    win_rate = len(wins) / len(trades) * 100
    
    return {
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'avg_pnl': avg_pnl,
    }

def main():
    entries = parse_execution_log()
    exits = parse_exit_log()
    matched = match_trades(entries, exits)
    
    old_strategy_trades = apply_old_strategy(matched)
    new_strategy_trades = apply_new_strategy(matched)
    
    old_stats = calculate_stats(old_strategy_trades)
    new_stats = calculate_stats(new_strategy_trades)
    
    print(f"\n{'='*70}")
    print("STRATEGY COMPARISON: OLD vs NEW")
    print(f"{'='*70}\n")
    
    print("OLD STRATEGY (first implementation):")
    print("  • Symbols: ETHUSD + BTCUSD")
    print("  • Side: DOWN only")
    print("  • Entry: >= $0.65")
    print("  • Quality: >= 500 (blocked < 500)")
    print()
    
    print("NEW STRATEGY (optimized):")
    print("  • Symbols: ETHUSD ONLY")
    print("  • Side: DOWN only")
    print("  • Entry: >= $0.65")
    print("  • Quality: NO FILTER")
    print()
    
    print(f"{'='*70}")
    print("HISTORICAL PERFORMANCE (on same 316-trade dataset)")
    print(f"{'='*70}\n")
    
    if old_stats:
        print("OLD STRATEGY RESULTS:")
        print(f"  Total Trades: {old_stats['total_trades']}")
        print(f"  Win/Loss: {old_stats['wins']}W-{old_stats['losses']}L")
        print(f"  Win Rate: {old_stats['win_rate']:.1f}%")
        print(f"  Total P&L: ${old_stats['total_pnl']:.2f}")
        print(f"  Avg P&L: ${old_stats['avg_pnl']:.3f} per trade")
    else:
        print("OLD STRATEGY RESULTS: NO TRADES (quality filter blocked everything)")
    
    print()
    
    if new_stats:
        print("NEW STRATEGY RESULTS:")
        print(f"  Total Trades: {new_stats['total_trades']}")
        print(f"  Win/Loss: {new_stats['wins']}W-{new_stats['losses']}L")
        print(f"  Win Rate: {new_stats['win_rate']:.1f}%")
        print(f"  Total P&L: ${new_stats['total_pnl']:.2f}")
        print(f"  Avg P&L: ${new_stats['avg_pnl']:.3f} per trade")
    else:
        print("NEW STRATEGY RESULTS: NO TRADES")
    
    print()
    print(f"{'='*70}")
    print("COMPARISON")
    print(f"{'='*70}\n")
    
    if old_stats and new_stats:
        trade_diff = new_stats['total_trades'] - old_stats['total_trades']
        wr_diff = new_stats['win_rate'] - old_stats['win_rate']
        pnl_diff = new_stats['total_pnl'] - old_stats['total_pnl']
        avg_diff = new_stats['avg_pnl'] - old_stats['avg_pnl']
        
        print(f"Trades: {new_stats['total_trades']} vs {old_stats['total_trades']} ({trade_diff:+d} trades)")
        print(f"Win Rate: {new_stats['win_rate']:.1f}% vs {old_stats['win_rate']:.1f}% ({wr_diff:+.1f}%)")
        print(f"Total P&L: ${new_stats['total_pnl']:.2f} vs ${old_stats['total_pnl']:.2f} (${pnl_diff:+.2f})")
        print(f"Avg P&L: ${new_stats['avg_pnl']:.3f} vs ${old_stats['avg_pnl']:.3f} (${avg_diff:+.3f})")
        
        print()
        print("KEY CHANGES:")
        if trade_diff > 0:
            pct = (trade_diff / old_stats['total_trades']) * 100
            print(f"  ✅ {abs(trade_diff)} MORE trades (+{pct:.0f}%) by removing quality filter")
        elif trade_diff < 0:
            pct = (abs(trade_diff) / old_stats['total_trades']) * 100
            print(f"  ⚠️  {abs(trade_diff)} FEWER trades (-{pct:.0f}%)")
        
        if wr_diff > 0:
            print(f"  ✅ Win rate IMPROVED by {wr_diff:.1f}%")
        elif wr_diff < 0:
            print(f"  ❌ Win rate DECLINED by {abs(wr_diff):.1f}%")
        
        if pnl_diff > 0:
            print(f"  ✅ Total P&L IMPROVED by ${pnl_diff:.2f}")
        elif pnl_diff < 0:
            print(f"  ❌ Total P&L DECLINED by ${abs(pnl_diff):.2f}")
        
        if avg_diff > 0:
            pct = (avg_diff / abs(old_stats['avg_pnl'])) * 100 if old_stats['avg_pnl'] != 0 else 0
            print(f"  ✅ Avg per trade IMPROVED by ${avg_diff:.3f} ({pct:.0f}%)")
        elif avg_diff < 0:
            pct = (abs(avg_diff) / abs(old_stats['avg_pnl'])) * 100 if old_stats['avg_pnl'] != 0 else 0
            print(f"  ❌ Avg per trade DECLINED by ${abs(avg_diff):.3f} ({pct:.0f}%)")
    
    elif old_stats and not new_stats:
        print("❌ NEW STRATEGY: No trades would have been taken (too restrictive)")
    elif not old_stats and new_stats:
        print("✅ NEW STRATEGY: Now captures trades that old strategy missed")
        print(f"   {new_stats['total_trades']} trades at {new_stats['win_rate']:.1f}% WR")
    
    print()
    print(f"{'='*70}")
    print("TRADES BREAKDOWN")
    print(f"{'='*70}\n")
    
    # Show which trades old strategy would have taken
    old_trades_set = set((t['timestamp'], t['entry_price']) for t in old_strategy_trades)
    new_trades_set = set((t['timestamp'], t['entry_price']) for t in new_strategy_trades)
    
    only_new = new_trades_set - old_trades_set
    only_old = old_trades_set - new_trades_set
    both = old_trades_set & new_trades_set
    
    print(f"Trades in BOTH strategies: {len(both)}")
    print(f"Trades ONLY in NEW strategy: {len(only_new)}")
    print(f"Trades ONLY in OLD strategy: {len(only_old)}")
    
    if only_new:
        # Calculate P&L of trades only in new
        only_new_trades = [t for t in new_strategy_trades if (t['timestamp'], t['entry_price']) in only_new]
        only_new_wins = sum(1 for t in only_new_trades if t['won'])
        only_new_losses = len(only_new_trades) - only_new_wins
        only_new_pnl = sum(t['pnl'] for t in only_new_trades)
        
        print(f"\n  NEW-ONLY trades performance: {only_new_wins}W-{only_new_losses}L, ${only_new_pnl:.2f} P&L")
        print(f"  (These would have been BLOCKED by old strategy's quality filter)")
    
    print()

if __name__ == "__main__":
    main()
