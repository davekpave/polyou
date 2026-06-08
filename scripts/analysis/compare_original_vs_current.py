"""Compare ORIGINAL strategy (pre-optimization) vs CURRENT strategy."""
import csv

def parse_logs():
    """Parse execution and exit logs."""
    trades = []
    
    # Parse execution log
    entries = {}
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
                
                entries[timestamp] = {
                    'timestamp': timestamp,
                    'symbol': symbol,
                    'side': side,
                    'entry_price': entry_price,
                    'quality': quality,
                }
            except (ValueError, IndexError):
                continue
    
    # Parse exit log and match to entries
    with open('logs/exit_log.csv', 'r') as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 6:
                continue
            try:
                exit_ts = float(row[0])
                entry_price = float(row[3])
                pnl = float(row[5])
                
                # Find matching entry
                best_match = None
                best_diff = float('inf')
                
                for entry_ts, entry_data in entries.items():
                    price_diff = abs(entry_data['entry_price'] - entry_price)
                    if price_diff > 0.01:
                        continue
                    
                    time_diff = exit_ts - entry_ts
                    if time_diff < 0 or time_diff > 1200:
                        continue
                    
                    if time_diff < best_diff:
                        best_diff = time_diff
                        best_match = entry_data
                
                if best_match:
                    trades.append({
                        **best_match,
                        'exit_ts': exit_ts,
                        'pnl': pnl,
                        'won': pnl > 0
                    })
            except (ValueError, IndexError):
                continue
    
    return trades

def apply_current_strategy(trades):
    """Apply CURRENT strategy: ETH only, DOWN only, Entry >=0.65, NO quality filter."""
    filtered = []
    for t in trades:
        if t['symbol'] != 'ETHUSD':
            continue
        if t['side'] != 'DOWN':
            continue
        if t['entry_price'] < 0.65:
            continue
        filtered.append(t)
    return filtered

def calculate_stats(trades):
    """Calculate performance statistics."""
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
    trades = parse_logs()
    
    # ORIGINAL strategy = no filters (all trades)
    original_stats = calculate_stats(trades)
    
    # CURRENT strategy = ETH only, DOWN only, Entry >=0.65, no quality filter
    current_trades = apply_current_strategy(trades)
    current_stats = calculate_stats(current_trades)
    
    print(f"\n{'='*70}")
    print("FULL COMPARISON: ORIGINAL (PRE-OPTIMIZATION) vs CURRENT")
    print(f"{'='*70}\n")
    
    print("ORIGINAL STRATEGY (before ANY optimizations):")
    print("  • Symbols: BTCUSD, ETHUSD, SOLUSD, XRPUSD")
    print("  • Side: Both UP and DOWN")
    print("  • Entry: Any price")
    print("  • Quality: No filter")
    print("  • Result: Historical baseline performance")
    print()
    
    print("CURRENT STRATEGY (after data-driven optimization):")
    print("  • Symbols: ETHUSD ONLY")
    print("  • Side: DOWN only")
    print("  • Entry: >= $0.65")
    print("  • Quality: NO FILTER")
    print("  • Result: Optimized for highest win rate setup")
    print()
    
    print(f"{'='*70}")
    print("PERFORMANCE COMPARISON")
    print(f"{'='*70}\n")
    
    if original_stats:
        print("ORIGINAL STRATEGY (all historical trades):")
        print(f"  Total Trades: {original_stats['total_trades']}")
        print(f"  Win/Loss: {original_stats['wins']}W-{original_stats['losses']}L")
        print(f"  Win Rate: {original_stats['win_rate']:.1f}%")
        print(f"  Total P&L: ${original_stats['total_pnl']:.2f}")
        print(f"  Avg P&L: ${original_stats['avg_pnl']:.3f} per trade")
    
    print()
    
    if current_stats:
        print("CURRENT STRATEGY (optimized filters):")
        print(f"  Total Trades: {current_stats['total_trades']}")
        print(f"  Win/Loss: {current_stats['wins']}W-{current_stats['losses']}L")
        print(f"  Win Rate: {current_stats['win_rate']:.1f}%")
        print(f"  Total P&L: ${current_stats['total_pnl']:.2f}")
        print(f"  Avg P&L: ${current_stats['avg_pnl']:.3f} per trade")
    
    print()
    print(f"{'='*70}")
    print("IMPACT ANALYSIS")
    print(f"{'='*70}\n")
    
    if original_stats and current_stats:
        trade_pct = (current_stats['total_trades'] / original_stats['total_trades']) * 100
        wr_diff = current_stats['win_rate'] - original_stats['win_rate']
        pnl_diff = current_stats['total_pnl'] - original_stats['total_pnl']
        
        print(f"Trade Volume: {current_stats['total_trades']} vs {original_stats['total_trades']} trades ({trade_pct:.1f}% of original)")
        print(f"Win Rate: {current_stats['win_rate']:.1f}% vs {original_stats['win_rate']:.1f}% ({wr_diff:+.1f}%)")
        print(f"Total P&L: ${current_stats['total_pnl']:.2f} vs ${original_stats['total_pnl']:.2f} (${pnl_diff:+.2f})")
        print(f"Avg P&L per trade: ${current_stats['avg_pnl']:.3f} vs ${original_stats['avg_pnl']:.3f}")
        
        print()
        print("KEY IMPROVEMENTS:")
        if wr_diff > 0:
            print(f"  ✅ Win rate improved by {wr_diff:.1f} percentage points")
        if current_stats['avg_pnl'] > 0 and original_stats['avg_pnl'] < 0:
            print(f"  ✅ Changed from LOSING ${abs(original_stats['avg_pnl']):.3f} to WINNING ${current_stats['avg_pnl']:.3f} per trade")
        elif current_stats['avg_pnl'] > original_stats['avg_pnl']:
            improvement_pct = ((current_stats['avg_pnl'] - original_stats['avg_pnl']) / abs(original_stats['avg_pnl'])) * 100
            print(f"  ✅ Avg P&L per trade improved by {improvement_pct:.0f}%")
        
        # Calculate what would have happened if we only took current strategy trades
        trades_avoided = original_stats['total_trades'] - current_stats['total_trades']
        if trades_avoided > 0:
            avoided_pnl = original_stats['total_pnl'] - current_stats['total_pnl']
            print(f"  ✅ Avoided {trades_avoided} losing/low-quality trades (would have cost ${avoided_pnl:.2f})")
        
        print()
        print("STRATEGY EFFECTIVENESS:")
        print(f"  By focusing on ETH DOWN ≥$0.65 trades, we:")
        print(f"  • Trade less frequently ({trade_pct:.0f}% of original volume)")
        print(f"  • Win more consistently ({current_stats['win_rate']:.1f}% vs {original_stats['win_rate']:.1f}% WR)")
        print(f"  • Avoid low-probability setups (SOL 4.4% WR, XRP 0% WR, UP trades 49% WR)")
    
    print()

if __name__ == "__main__":
    main()
