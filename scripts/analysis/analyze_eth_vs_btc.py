"""Deep dive analysis: ETH vs BTC performance."""
import csv
from collections import defaultdict

def parse_execution_log():
    """Parse execution_log.csv to get entry details."""
    trades = []
    with open('logs/execution_log.csv', 'r') as f:
        reader = csv.reader(f)
        next(reader, None)  # Skip header
        for row in reader:
            if len(row) < 10:
                continue
            try:
                timestamp = float(row[0])
                symbol = row[1]
                side = row[2]
                entry_price = float(row[4])  # snapshot_price
                quality = float(row[9])  # signal_quality
                
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
        next(reader, None)  # Skip header
        for row in reader:
            if len(row) < 6:
                continue
            try:
                timestamp = float(row[0])
                reason = row[2]
                entry_price = float(row[3])
                exit_price = float(row[4])
                pnl = float(row[5])
                
                exits.append({
                    'timestamp': timestamp,
                    'reason': reason,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
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

def analyze_deep_dive():
    """Main analysis function."""
    entries = parse_execution_log()
    exits = parse_exit_log()
    matched = match_trades(entries, exits)
    
    # Filter for DOWN side only (our target)
    down_trades = [t for t in matched if t['side'] == 'DOWN']
    
    # Filter for entry price >= $0.65 (our target)
    down_65plus = [t for t in down_trades if t['entry_price'] >= 0.65]
    
    # Separate by symbol
    eth_all = [t for t in down_trades if t['symbol'] == 'ETHUSD']
    btc_all = [t for t in down_trades if t['symbol'] == 'BTCUSD']
    
    eth_65plus = [t for t in down_65plus if t['symbol'] == 'ETHUSD']
    btc_65plus = [t for t in down_65plus if t['symbol'] == 'BTCUSD']
    
    print(f"\n{'='*70}")
    print(f"DEEP DIVE: ETH vs BTC (DOWN SIDE ONLY)")
    print(f"{'='*70}\n")
    
    # === ALL DOWN TRADES (any entry price) ===
    print(f"{'='*70}")
    print("PART 1: ALL DOWN TRADES (Any Entry Price)")
    print(f"{'='*70}\n")
    
    for symbol, trades in [('ETHUSD', eth_all), ('BTCUSD', btc_all)]:
        if not trades:
            continue
        
        wins = [t for t in trades if t['won']]
        losses = [t for t in trades if not t['won']]
        
        print(f"{symbol}:")
        print(f"  Total: {len(trades)} ({len(wins)}W-{len(losses)}L)")
        print(f"  Win Rate: {len(wins)/len(trades)*100:.1f}%")
        
        if wins:
            avg_win = sum(t['pnl'] for t in wins) / len(wins)
            total_win = sum(t['pnl'] for t in wins)
            print(f"  Winners: Avg +${avg_win:.2f}, Total +${total_win:.2f}")
        
        if losses:
            avg_loss = sum(t['pnl'] for t in losses) / len(losses)
            total_loss = sum(t['pnl'] for t in losses)
            print(f"  Losers: Avg ${avg_loss:.2f}, Total ${total_loss:.2f}")
        
        net_pnl = sum(t['pnl'] for t in trades)
        avg_pnl = net_pnl / len(trades)
        print(f"  Net P&L: ${net_pnl:.2f} (${avg_pnl:.3f} per trade)")
        
        # Entry price analysis
        avg_entry = sum(t['entry_price'] for t in trades) / len(trades)
        print(f"  Avg Entry Price: ${avg_entry:.3f}")
        
        # Quality analysis
        avg_quality = sum(t['quality'] for t in trades) / len(trades)
        print(f"  Avg Quality Score: {avg_quality:.0f}")
        print()
    
    # === DOWN TRADES WITH ENTRY >= $0.65 (our filter) ===
    print(f"{'='*70}")
    print("PART 2: DOWN TRADES WITH ENTRY >= $0.65 (Current Filter)")
    print(f"{'='*70}\n")
    
    for symbol, trades in [('ETHUSD', eth_65plus), ('BTCUSD', btc_65plus)]:
        if not trades:
            print(f"{symbol}: NO TRADES (all filtered out)\n")
            continue
        
        wins = [t for t in trades if t['won']]
        losses = [t for t in trades if not t['won']]
        
        print(f"{symbol}:")
        print(f"  Total: {len(trades)} ({len(wins)}W-{len(losses)}L)")
        print(f"  Win Rate: {len(wins)/len(trades)*100:.1f}%")
        
        if wins:
            avg_win = sum(t['pnl'] for t in wins) / len(wins)
            total_win = sum(t['pnl'] for t in wins)
            print(f"  Winners: Avg +${avg_win:.2f}, Total +${total_win:.2f}")
        
        if losses:
            avg_loss = sum(t['pnl'] for t in losses) / len(losses)
            total_loss = sum(t['pnl'] for t in losses)
            print(f"  Losers: Avg ${avg_loss:.2f}, Total ${total_loss:.2f}")
        
        net_pnl = sum(t['pnl'] for t in trades)
        avg_pnl = net_pnl / len(trades)
        print(f"  Net P&L: ${net_pnl:.2f} (${avg_pnl:.3f} per trade)")
        
        # Entry price analysis
        avg_entry = sum(t['entry_price'] for t in trades) / len(trades)
        print(f"  Avg Entry Price: ${avg_entry:.3f}")
        
        # Quality analysis
        avg_quality = sum(t['quality'] for t in trades) / len(trades)
        print(f"  Avg Quality Score: {avg_quality:.0f}")
        print()
    
    # === BTC BREAKDOWN BY ENTRY PRICE ===
    if btc_all:
        print(f"{'='*70}")
        print("PART 3: BTC BREAKDOWN BY ENTRY PRICE")
        print(f"{'='*70}\n")
        
        btc_under_65 = [t for t in btc_all if t['entry_price'] < 0.65]
        btc_over_65 = [t for t in btc_all if t['entry_price'] >= 0.65]
        
        for label, trades in [('BTC < $0.65', btc_under_65), ('BTC >= $0.65', btc_over_65)]:
            if not trades:
                print(f"{label}: NO TRADES\n")
                continue
            
            wins = [t for t in trades if t['won']]
            losses = [t for t in trades if not t['won']]
            
            print(f"{label}:")
            print(f"  Total: {len(trades)} ({len(wins)}W-{len(losses)}L)")
            if trades:
                print(f"  Win Rate: {len(wins)/len(trades)*100:.1f}%")
                net_pnl = sum(t['pnl'] for t in trades)
                avg_pnl = net_pnl / len(trades)
                print(f"  Net P&L: ${net_pnl:.2f} (${avg_pnl:.3f} per trade)")
                avg_entry = sum(t['entry_price'] for t in trades) / len(trades)
                print(f"  Avg Entry: ${avg_entry:.3f}")
            print()
    
    # === QUALITY SCORE COMPARISON ===
    print(f"{'='*70}")
    print("PART 4: QUALITY SCORE DISTRIBUTION")
    print(f"{'='*70}\n")
    
    for symbol, trades in [('ETHUSD >= $0.65', eth_65plus), ('BTCUSD >= $0.65', btc_65plus)]:
        if not trades:
            continue
        
        # Quality brackets
        q_under_500 = [t for t in trades if t['quality'] < 500]
        q_500_1000 = [t for t in trades if 500 <= t['quality'] < 1000]
        q_over_1000 = [t for t in trades if t['quality'] >= 1000]
        
        print(f"{symbol}:")
        for label, subset in [('< 500', q_under_500), ('500-1000', q_500_1000), ('> 1000', q_over_1000)]:
            if subset:
                wins = sum(1 for t in subset if t['won'])
                losses = len(subset) - wins
                wr = wins/len(subset)*100 if subset else 0
                print(f"  Quality {label:10s}: {len(subset):3d} trades ({wins}W-{losses}L, {wr:.1f}% WR)")
        print()
    
    # === FINAL RECOMMENDATION ===
    print(f"{'='*70}")
    print("SUMMARY & RECOMMENDATION")
    print(f"{'='*70}\n")
    
    if eth_65plus:
        eth_wr = sum(1 for t in eth_65plus if t['won']) / len(eth_65plus) * 100
        eth_pnl = sum(t['pnl'] for t in eth_65plus) / len(eth_65plus)
        print(f"ETH DOWN >= $0.65: {len(eth_65plus)} trades, {eth_wr:.1f}% WR, ${eth_pnl:.3f}/trade")
    
    if btc_65plus:
        btc_wr = sum(1 for t in btc_65plus if t['won']) / len(btc_65plus) * 100
        btc_pnl = sum(t['pnl'] for t in btc_65plus) / len(btc_65plus)
        print(f"BTC DOWN >= $0.65: {len(btc_65plus)} trades, {btc_wr:.1f}% WR, ${btc_pnl:.3f}/trade")
    
    if eth_65plus and btc_65plus:
        combined = eth_65plus + btc_65plus
        combined_wr = sum(1 for t in combined if t['won']) / len(combined) * 100
        combined_pnl = sum(t['pnl'] for t in combined) / len(combined)
        print(f"COMBINED: {len(combined)} trades, {combined_wr:.1f}% WR, ${combined_pnl:.3f}/trade")
    
    print()

if __name__ == "__main__":
    analyze_deep_dive()
